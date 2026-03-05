"""Binance WS feeds for BTC/ETH/SOL/XRP."""

from __future__ import annotations

import asyncio
import json
import time
from collections import deque
from dataclasses import dataclass, field

import websockets

from core.event_bus import bus
from core.logger import logger
from core.state import state

STREAMS = {
    "BTC": "wss://stream.binance.com:9443/ws/btcusdt@trade",
    "ETH": "wss://stream.binance.com:9443/ws/ethusdt@trade",
    "SOL": "wss://stream.binance.com:9443/ws/solusdt@trade",
    "XRP": "wss://stream.binance.com:9443/ws/xrpusdt@trade",
}


@dataclass
class AssetBuffer:
    prices: deque[float] = field(default_factory=lambda: deque(maxlen=1000))
    volumes: deque[float] = field(default_factory=lambda: deque(maxlen=1000))
    timestamps: deque[float] = field(default_factory=lambda: deque(maxlen=1000))
    sides: deque[str] = field(default_factory=lambda: deque(maxlen=1000))
    accelerations: deque[float] = field(default_factory=lambda: deque(maxlen=1000))

    def add(self, price: float, volume: float, ts: float, side: str) -> None:
        self.prices.append(price)
        self.volumes.append(volume)
        self.timestamps.append(ts)
        self.sides.append(side)

    def _price_ago(self, secs: float) -> float:
        if not self.timestamps:
            return 0.0
        tgt = self.timestamps[-1] - secs
        for i in range(len(self.timestamps) - 1, -1, -1):
            if self.timestamps[i] <= tgt:
                return self.prices[i]
        return self.prices[0]

    def _avg_vol(self, secs: float) -> float:
        if not self.timestamps:
            return 0.0
        cutoff = self.timestamps[-1] - secs
        vals = [v for v, t in zip(self.volumes, self.timestamps) if t >= cutoff]
        return sum(vals) / len(vals) if vals else 0.0

    def _rsi_14(self) -> float:
        if len(self.prices) < 15:
            return 50.0
        gains = 0.0
        losses = 0.0
        for i in range(-14, 0):
            d = self.prices[i] - self.prices[i - 1]
            if d > 0:
                gains += d
            else:
                losses += abs(d)
        ag = gains / 14
        al = losses / 14 if losses else 1e-9
        rs = ag / al
        return 100 - (100 / (1 + rs))

    def _buy_pct(self, secs: float = 30) -> float:
        if not self.timestamps:
            return 0.5
        cutoff = self.timestamps[-1] - secs
        sides = [s for s, t in zip(self.sides, self.timestamps) if t >= cutoff]
        if not sides:
            return 0.5
        return sum(1 for s in sides if s == 'BUY') / len(sides)

    def _vwap(self, secs: float = 1800) -> float:
        if not self.timestamps:
            return 0.0
        cutoff = self.timestamps[-1] - secs
        pv = [(p * v, v) for p, v, t in zip(self.prices, self.volumes, self.timestamps) if t >= cutoff]
        tv = sum(v for _, v in pv)
        if tv <= 0:
            return self.prices[-1]
        return sum(x for x, _ in pv) / tv

    def _consecutive(self) -> int:
        if not self.sides:
            return 0
        last = self.sides[-1]
        c = 0
        for s in reversed(self.sides):
            if s != last:
                break
            c += 1
        return c if last == 'BUY' else -c

    def metrics(self) -> dict[str, float]:
        if len(self.prices) < 3:
            return {
                'velocity_10s': 0.0, 'velocity_30s': 0.0, 'velocity_60s': 0.0, 'velocity_300s': 0.0,
                'acceleration': 0.0, 'jerk': 0.0, 'volume_ratio_10_60': 1.0, 'volume_ratio_60_300': 1.0,
                'buy_volume_pct': 0.5, 'rsi_14': 50.0, 'vwap_deviation': 0.0, 'consecutive_direction': 0,
                'pct_change_60s': 0.0,
            }
        p = self.prices[-1]
        p10 = self._price_ago(10)
        p30 = self._price_ago(30)
        p60 = self._price_ago(60)
        p300 = self._price_ago(300)
        v10 = (p - p10) / 10 if p10 else 0.0
        v30 = (p - p30) / 30 if p30 else 0.0
        v60 = (p - p60) / 60 if p60 else 0.0
        v300 = (p - p300) / 300 if p300 else 0.0
        accel = v10 - v30
        self.accelerations.append(accel)
        jerk = accel - self.accelerations[-6] if len(self.accelerations) > 6 else 0.0
        vol10 = self._avg_vol(10)
        vol60 = self._avg_vol(60)
        vol300 = self._avg_vol(300)
        vwap = self._vwap(1800)
        return {
            'velocity_10s': v10,
            'velocity_30s': v30,
            'velocity_60s': v60,
            'velocity_300s': v300,
            'acceleration': accel,
            'jerk': jerk,
            'volume_ratio_10_60': vol10 / vol60 if vol60 else 1.0,
            'volume_ratio_60_300': vol60 / vol300 if vol300 else 1.0,
            'buy_volume_pct': self._buy_pct(30),
            'rsi_14': self._rsi_14(),
            'vwap_deviation': ((p - vwap) / vwap) if vwap else 0.0,
            'consecutive_direction': self._consecutive(),
            'pct_change_60s': ((p - p60) / p60) if p60 else 0.0,
        }


class BinanceFeed:
    def __init__(self) -> None:
        self.buffers = {a: AssetBuffer() for a in STREAMS}

    async def _run_asset(self, asset: str, url: str) -> None:
        backoff = 0.1
        while True:
            try:
                async with websockets.connect(url, ping_interval=20, ping_timeout=20) as ws:
                    await state.set(f'feed.binance.{asset}.connected', True)
                    await state.set(f'feed.binance.{asset}.last_tick', time.time())
                    await bus.publish('FEED_RECONNECTED', {'feed': 'binance', 'asset': asset})
                    backoff = 0.1
                    async for raw in ws:
                        data = json.loads(raw)
                        px = float(data.get('p', 0.0))
                        vol = float(data.get('q', 0.0))
                        ts = float(data.get('T', int(time.time() * 1000))) / 1000
                        side = 'SELL' if data.get('m', False) else 'BUY'

                        buf = self.buffers[asset]
                        buf.add(px, vol, ts, side)
                        m = buf.metrics()

                        await state.set(f'price.{asset}.price', px)
                        await state.set(f'price.{asset}.timestamp', ts)
                        for k, v in m.items():
                            await state.set(f'price.{asset}.{k}', v)
                        await state.set(f'feed.binance.{asset}.last_tick', time.time())
                        state.append_list(f'history.{asset}.velocity_60s', float(m['velocity_60s']), maxlen=1800)

                        payload = {'asset': asset, 'price': px, 'volume': vol, 'timestamp': ts, 'side': side, **m}
                        await bus.publish('PRICE_TICK', payload)
                        if abs(float(m['pct_change_60s'])) > 0.003:
                            await bus.publish('MAJOR_MOVE', payload)
                        if float(m['volume_ratio_10_60']) > 3.0:
                            await bus.publish('VOLUME_SPIKE', payload)
                        if abs(float(m['acceleration'])) > 0.0004 and (float(m['acceleration']) * float(m['velocity_30s'])) < 0:
                            await bus.publish('VELOCITY_REVERSAL', payload)
            except Exception as exc:  # noqa: BLE001
                await state.set(f'feed.binance.{asset}.connected', False)
                await bus.publish('FEED_DISCONNECTED', {'feed': 'binance', 'asset': asset, 'error': str(exc)})
                logger.warning('binance_reconnect', asset=asset, sleep=backoff, error=str(exc))
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 5.0)

    async def run(self) -> None:
        await asyncio.gather(*[self._run_asset(a, u) for a, u in STREAMS.items()])


async def start_binance_feeds() -> None:
    await BinanceFeed().run()
