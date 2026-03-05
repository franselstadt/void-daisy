"""Binance WS feeds for BTC/ETH/SOL/XRP."""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field

import ujson
import websockets

from core.event_bus import bus
from loguru import logger
from core.state import state

ASSETS = {
    "BTC": "btcusdt@trade",
    "ETH": "ethusdt@trade",
    "SOL": "solusdt@trade",
    "XRP": "xrpusdt@trade",
}
WS = "wss://stream.binance.com:9443/ws"


@dataclass
class AssetBuffer:
    prices: deque = field(default_factory=lambda: deque(maxlen=2000))
    volumes: deque = field(default_factory=lambda: deque(maxlen=2000))
    times: deque = field(default_factory=lambda: deque(maxlen=2000))
    sides: deque = field(default_factory=lambda: deque(maxlen=2000))
    _vwap_pv: float = 0.0
    _vwap_v: float = 0.0

    def push(self, price: float, volume: float, ts: float, side: str) -> None:
        self.prices.append(price)
        self.volumes.append(volume)
        self.times.append(ts)
        self.sides.append(side)
        self._vwap_pv += price * volume
        self._vwap_v += volume
        if len(self.prices) % 10000 == 0:
            self._vwap_pv = price * volume
            self._vwap_v = volume

    def vel(self, secs: int) -> float:
        if len(self.times) < 2:
            return 0.0
        now = self.times[-1]
        olds = [p for p, t in zip(self.prices, self.times) if t >= now - secs]
        return (self.prices[-1] - olds[0]) / secs if olds else 0.0

    def vol_ratio(self, short: int = 10, long: int = 60) -> float:
        now = self.times[-1] if self.times else 0
        sv = [v for v, t in zip(self.volumes, self.times) if t >= now - short]
        lv = [v for v, t in zip(self.volumes, self.times) if t >= now - long]
        if not lv or not sv:
            return 1.0
        return (sum(sv) / len(sv)) / (sum(lv) / len(lv))

    def buy_pct(self, secs: int = 30) -> float:
        now = self.times[-1] if self.times else 0
        r = [s for s, t in zip(self.sides, self.times) if t >= now - secs]
        return sum(1 for s in r if s == "BUY") / len(r) if r else 0.5

    def rsi(self, period: int = 14) -> float:
        if len(self.prices) < period * 2:
            return 50.0
        px = list(self.prices)[-(period * 2):]
        g = [max(0, px[i] - px[i - 1]) for i in range(1, len(px))]
        l = [max(0, px[i - 1] - px[i]) for i in range(1, len(px))]
        ag = sum(g[-period:]) / period
        al = sum(l[-period:]) / period
        return 100 - (100 / (1 + ag / al)) if al > 0 else 100.0

    def vwap(self) -> float:
        return self._vwap_pv / self._vwap_v if self._vwap_v else 0.0

    def consec(self) -> int:
        if len(self.prices) < 2:
            return 0
        px = list(self.prices)[-50:]
        direction = 1 if px[-1] > px[-2] else -1
        count = 0
        for i in range(len(px) - 1, 0, -1):
            d = 1 if px[i] > px[i - 1] else -1
            if d == direction:
                count += direction
            else:
                break
        return count


bufs = {a: AssetBuffer() for a in ASSETS}


async def _stream(asset: str, sym: str) -> None:
    delay = 0.1
    while True:
        try:
            async with websockets.connect(
                f"{WS}/{sym}",
                ping_interval=20, ping_timeout=10,
                close_timeout=5, max_size=2**20,
            ) as ws:
                delay = 0.1
                await state.set(f"feed.binance.{asset}.connected", True)
                logger.info(f"Binance {asset} connected")
                async for msg in ws:
                    d = ujson.loads(msg)
                    price = float(d["p"])
                    vol = float(d["q"])
                    ts = d["T"] / 1000.0
                    side = "BUY" if not d["m"] else "SELL"

                    buf = bufs[asset]
                    buf.push(price, vol, ts, side)

                    v10 = buf.vel(10)
                    v30 = buf.vel(30)
                    v60 = buf.vel(60)
                    v300 = buf.vel(300)
                    vwap_val = buf.vwap()

                    k = state.get(f"learning.l2.kalman.{asset}", {}) or {}

                    tick = {
                        "asset": asset,
                        "price": price,
                        "velocity_10s": v10,
                        "velocity_30s": v30,
                        "velocity_60s": v60,
                        "velocity_300s": v300,
                        "acceleration": v10 - v30,
                        "jerk": (v10 - v30) - float(state.get(f"price.{asset}.acceleration", 0)),
                        "volume_ratio_10_60": buf.vol_ratio(10, 60),
                        "volume_ratio_60_300": buf.vol_ratio(60, 300),
                        "buy_volume_pct": buf.buy_pct(30),
                        "rsi_14": buf.rsi(),
                        "vwap_deviation": (price - vwap_val) / vwap_val if vwap_val else 0,
                        "consecutive_direction": buf.consec(),
                        "kalman_price": k.get("x_price", price) if isinstance(k, dict) else price,
                        "kalman_velocity": k.get("x_velocity", v30) if isinstance(k, dict) else v30,
                        "timestamp": ts,
                    }

                    state.set_sync(f"price.{asset}", tick)
                    await state.set(f"feed.binance.{asset}.last_tick", ts)
                    await bus.publish("PRICE_TICK", tick)

                    state.append_list(f"history.{asset}.velocity_60s", float(v60), maxlen=1800)

                    pct = v60 * 60 / price if price else 0
                    if abs(pct) > 0.003:
                        await bus.publish("MAJOR_MOVE", {
                            **tick, "pct_change": pct,
                            "direction": "UP" if v60 > 0 else "DOWN",
                        })

                    if buf.vol_ratio(10, 60) > 3.0:
                        await bus.publish("VOLUME_SPIKE", tick)

        except Exception as e:
            await state.set(f"feed.binance.{asset}.connected", False)
            logger.warning(f"Binance {asset} dropped: {e} — retry in {delay}s")
            await asyncio.sleep(delay)
            delay = min(delay * 2, 5.0)


async def start_binance_feeds() -> None:
    await asyncio.gather(*[_stream(a, s) for a, s in ASSETS.items()])
