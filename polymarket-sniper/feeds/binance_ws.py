"""Binance multi-stream websocket ingestion."""

from __future__ import annotations

import asyncio
import json
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

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

    prices: deque[float] = field(default_factory=lambda: deque(maxlen=500))
    volumes: deque[float] = field(default_factory=lambda: deque(maxlen=500))
    timestamps: deque[float] = field(default_factory=lambda: deque(maxlen=500))
    sides: deque[str] = field(default_factory=lambda: deque(maxlen=500))

    def add(self, price: float, volume: float, timestamp: float, side: str) -> None:
        """Append latest tick."""
        self.prices.append(price)
        self.volumes.append(volume)
        self.timestamps.append(timestamp)
        self.sides.append(side)

    def _price_seconds_ago(self, seconds: float) -> float | None:
        if not self.timestamps:
            return None
        target = self.timestamps[-1] - seconds
        for idx in range(len(self.timestamps) - 1, -1, -1):
            if self.timestamps[idx] <= target:
                return self.prices[idx]
        return self.prices[0] if self.prices else None

    def _avg_volume_window(self, seconds: float) -> float:
        if not self.timestamps:
            return 0.0
        cutoff = self.timestamps[-1] - seconds
        selected = [v for v, ts in zip(self.volumes, self.timestamps) if ts >= cutoff]
        return sum(selected) / len(selected) if selected else 0.0

    def _rsi_14(self) -> float:
        if len(self.prices) < 15:
            return 50.0
        gains, losses = [], []
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

    def metrics(self) -> dict[str, float | bool]:
        """Compute all required momentum metrics."""
        if len(self.prices) < 2:
            return {
                "velocity_10s": 0.0,
                "velocity_30s": 0.0,
                "velocity_60s": 0.0,
                "acceleration": 0.0,
                "volume_ratio": 1.0,
                "rsi_14": 50.0,
                "accelerating": False,
                "pct_change_60s": 0.0,
            }

        p_now = self.prices[-1]
        p10 = self._price_seconds_ago(10) or p_now
        p30 = self._price_seconds_ago(30) or p_now
        p60 = self._price_seconds_ago(60) or p_now

        v10 = (p_now - p10) / 10
        v30 = (p_now - p30) / 30
        v60 = (p_now - p60) / 60
        vol10 = self._avg_volume_window(10)
        vol60 = self._avg_volume_window(60)

        return {
            "velocity_10s": v10,
            "velocity_30s": v30,
            "velocity_60s": v60,
            "acceleration": v10 - v30,
            "volume_ratio": vol10 / vol60 if vol60 > 0 else 1.0,
            "rsi_14": self._rsi_14(),
            "accelerating": abs(v10) > abs(v30),
            "pct_change_60s": ((p_now - p60) / p60) if p60 else 0.0,
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
                    logger.info("binance_connected", asset=asset)
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

                        latest_spot = await self.state.get("latest_spot", default={})
                        latest_spot[asset] = price
                        await self.state.set("latest_spot", value=latest_spot)

                        tick = {
                            "asset": asset,
                            "price": price,
                            "volume": volume,
                            "timestamp": ts,
                            "side": side,
                            **metrics,
                        }
                        latest = await self.state.get("latest_ticks", default={})
                        latest[asset] = tick
                        await self.state.set("latest_ticks", value=latest)

                        await bus.publish("PRICE_TICK", tick)
                        if abs(float(metrics["pct_change_60s"])) > 0.003:
                            await bus.publish("MAJOR_MOVE", tick)
            except Exception as exc:  # noqa: BLE001
                await self._set_connected(asset, False)
                await bus.publish("FEED_DISCONNECTED", {"feed": "binance", "asset": asset, "error": str(exc)})
                logger.warning("binance_disconnected", asset=asset, error=str(exc), reconnect_in=backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 5.0)

    async def run(self) -> None:
        """Run all streams forever."""
        await asyncio.gather(*[self._run_asset(asset, url) for asset, url in STREAMS.items()])


async def start_binance_feeds(state: AppState) -> None:
    """Entrypoint helper for main orchestration."""
    await BinanceFeed(state).run()
