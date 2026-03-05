"""Binance multi-stream websocket ingestion."""

from __future__ import annotations

import asyncio
import json
import time
from collections import deque
from dataclasses import dataclass, field

import websockets

from core.event_bus import bus
from core.logger import logger
from core.state import AppState

STREAMS = {
    "BTC": "wss://stream.binance.com:9443/ws/btcusdt@trade",
    "ETH": "wss://stream.binance.com:9443/ws/ethusdt@trade",
    "SOL": "wss://stream.binance.com:9443/ws/solusdt@trade",
    "XRP": "wss://stream.binance.com:9443/ws/xrpusdt@trade",
}


@dataclass
class AssetBuffer:
    """Bounded tick buffers for rolling signal calculations."""

    prices: deque[float] = field(default_factory=lambda: deque(maxlen=1000))
    volumes: deque[float] = field(default_factory=lambda: deque(maxlen=1000))
    timestamps: deque[float] = field(default_factory=lambda: deque(maxlen=1000))
    sides: deque[str] = field(default_factory=lambda: deque(maxlen=1000))
    accelerations: deque[float] = field(default_factory=lambda: deque(maxlen=1000))
    v60s_series: deque[float] = field(default_factory=lambda: deque(maxlen=60))

    def add(self, price: float, volume: float, timestamp: float, side: str) -> None:
        self.prices.append(price)
        self.volumes.append(volume)
        self.timestamps.append(timestamp)
        self.sides.append(side)

    def _price_seconds_ago(self, seconds: float) -> float:
        if not self.timestamps:
            return 0.0
        target = self.timestamps[-1] - seconds
        for i in range(len(self.timestamps) - 1, -1, -1):
            if self.timestamps[i] <= target:
                return self.prices[i]
        return self.prices[0]

    def _avg_volume(self, seconds: float) -> float:
        if not self.timestamps:
            return 0.0
        cutoff = self.timestamps[-1] - seconds
        values = [v for v, ts in zip(self.volumes, self.timestamps) if ts >= cutoff]
        return sum(values) / len(values) if values else 0.0

    def _buy_volume_pct(self, seconds: float = 30.0) -> float:
        if not self.timestamps:
            return 0.5
        cutoff = self.timestamps[-1] - seconds
        slice_sides = [s for s, ts in zip(self.sides, self.timestamps) if ts >= cutoff]
        if not slice_sides:
            return 0.5
        buys = sum(1 for s in slice_sides if s == "BUY")
        return buys / len(slice_sides)

    def _consecutive_direction(self) -> int:
        if not self.sides:
            return 0
        last = self.sides[-1]
        count = 0
        for side in reversed(self.sides):
            if side != last:
                break
            count += 1
        return count

    def _rsi_14(self) -> float:
        if len(self.prices) < 15:
            return 50.0
        gains: list[float] = []
        losses: list[float] = []
        for i in range(-14, 0):
            delta = self.prices[i] - self.prices[i - 1]
            if delta >= 0:
                gains.append(delta)
            else:
                losses.append(abs(delta))
        avg_gain = sum(gains) / 14
        avg_loss = sum(losses) / 14 if losses else 1e-9
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def _vwap(self, seconds: float = 1800.0) -> float:
        if not self.timestamps:
            return 0.0
        cutoff = self.timestamps[-1] - seconds
        pv = [(p * v, v) for p, v, ts in zip(self.prices, self.volumes, self.timestamps) if ts >= cutoff]
        total_v = sum(v for _, v in pv)
        return sum(x for x, _ in pv) / total_v if total_v > 0 else self.prices[-1]

    def metrics(self) -> dict[str, float | bool]:
        if len(self.prices) < 3:
            return {
                "velocity_10s": 0.0,
                "velocity_30s": 0.0,
                "velocity_60s": 0.0,
                "velocity_300s": 0.0,
                "acceleration": 0.0,
                "jerk": 0.0,
                "volume_ratio_10_60": 1.0,
                "volume_ratio_60_300": 1.0,
                "volume_ratio_300_1800": 1.0,
                "buy_volume_pct": 0.5,
                "rsi_14": 50.0,
                "vwap_deviation": 0.0,
                "consecutive_direction": 0,
                "pct_change_60s": 0.0,
            }

        p_now = self.prices[-1]
        p10 = self._price_seconds_ago(10)
        p30 = self._price_seconds_ago(30)
        p60 = self._price_seconds_ago(60)
        p300 = self._price_seconds_ago(300)
        v10 = (p_now - p10) / 10 if p10 else 0.0
        v30 = (p_now - p30) / 30 if p30 else 0.0
        v60 = (p_now - p60) / 60 if p60 else 0.0
        v300 = (p_now - p300) / 300 if p300 else 0.0
        accel = v10 - v30
        self.accelerations.append(accel)
        jerk = accel - self.accelerations[-6] if len(self.accelerations) > 6 else 0.0
        self.v60s_series.append(v60)

        vol10 = self._avg_volume(10)
        vol60 = self._avg_volume(60)
        vol300 = self._avg_volume(300)
        vol1800 = self._avg_volume(1800)
        vwap30 = self._vwap(1800)
        return {
            "velocity_10s": v10,
            "velocity_30s": v30,
            "velocity_60s": v60,
            "velocity_300s": v300,
            "acceleration": accel,
            "jerk": jerk,
            "volume_ratio_10_60": vol10 / vol60 if vol60 else 1.0,
            "volume_ratio_60_300": vol60 / vol300 if vol300 else 1.0,
            "volume_ratio_300_1800": vol300 / vol1800 if vol1800 else 1.0,
            "buy_volume_pct": self._buy_volume_pct(30),
            "rsi_14": self._rsi_14(),
            "vwap_deviation": ((p_now - vwap30) / vwap30) if vwap30 else 0.0,
            "consecutive_direction": self._consecutive_direction(),
            "pct_change_60s": ((p_now - p60) / p60) if p60 else 0.0,
            "v60s_series": list(self.v60s_series),
        }


class BinanceFeed:
    """Runs 4 Binance trade streams concurrently with reconnect."""

    def __init__(self, state: AppState) -> None:
        self.state = state
        self.buffers = {asset: AssetBuffer() for asset in STREAMS}

    async def _set_connected(self, asset: str, connected: bool) -> None:
        snap = await self.state.get("feed", "binance", default={})
        snap[asset] = {"connected": connected, "last_seen": time.time()}
        await self.state.set("feed", "binance", value=snap)

    async def _run_asset(self, asset: str, url: str) -> None:
        backoff = 0.1
        while True:
            try:
                async with websockets.connect(url, ping_interval=20, ping_timeout=20) as ws:
                    await self._set_connected(asset, True)
                    await bus.publish("FEED_RECONNECTED", {"feed": "binance", "asset": asset})
                    backoff = 0.1
                    async for raw in ws:
                        data = json.loads(raw)
                        price = float(data.get("p", 0.0))
                        volume = float(data.get("q", 0.0))
                        ts = float(data.get("T", int(time.time() * 1000))) / 1000
                        side = "SELL" if data.get("m", False) else "BUY"

                        buf = self.buffers[asset]
                        buf.add(price, volume, ts, side)
                        metrics = buf.metrics()
                        tick = {"asset": asset, "price": price, "volume": volume, "timestamp": ts, "side": side, **metrics}

                        latest_spot = await self.state.get("latest_spot", default={})
                        latest_spot[asset] = price
                        await self.state.set("latest_spot", value=latest_spot)
                        latest_ticks = await self.state.get("latest_ticks", default={})
                        latest_ticks[asset] = tick
                        await self.state.set("latest_ticks", value=latest_ticks)

                        feed_binance = await self.state.get("feed", "binance", default={})
                        feed_binance.setdefault(asset, {})
                        feed_binance[asset]["v60s_series"] = metrics["v60s_series"]
                        feed_binance[asset]["volume_ratio_300_1800"] = metrics["volume_ratio_300_1800"]
                        await self.state.set("feed", "binance", value=feed_binance)

                        await bus.publish("PRICE_TICK", tick)
                        if abs(float(metrics["pct_change_60s"])) > 0.003:
                            await bus.publish("MAJOR_MOVE", tick)
                        if float(metrics["volume_ratio_10_60"]) > 3.0:
                            await bus.publish("VOLUME_SPIKE", tick)
                        if abs(float(metrics["acceleration"])) > 0.0004 and (float(metrics["acceleration"]) * float(metrics["velocity_30s"])) < 0:
                            await bus.publish("VELOCITY_REVERSAL", tick)
            except Exception as exc:  # noqa: BLE001
                await self._set_connected(asset, False)
                await bus.publish("FEED_DISCONNECTED", {"feed": "binance", "asset": asset, "error": str(exc)})
                logger.warning("binance_disconnected", asset=asset, error=str(exc), reconnect_in=backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 5.0)

    async def run(self) -> None:
        await asyncio.gather(*[self._run_asset(asset, url) for asset, url in STREAMS.items()])


async def start_binance_feeds(state: AppState) -> None:
    """Entrypoint helper for main orchestration."""
    await BinanceFeed(state).run()
