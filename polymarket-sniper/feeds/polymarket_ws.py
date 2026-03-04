"""Polymarket market stream and active market subscription manager."""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from typing import Any

import aiohttp
import websockets

from core.event_bus import bus
from core.logger import logger
from core.state import AppState

GAMMA_URL = "https://gamma-api.polymarket.com/markets"
WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"


class PolymarketFeed:
    """Maintains market subscriptions and publishes normalized ticks."""

    def __init__(self, state: AppState) -> None:
        self.state = state
        self._market_map: dict[str, list[str]] = {"BTC": [], "ETH": [], "SOL": [], "XRP": []}
        self._subscribed_tokens: set[str] = set()
        self._prev_prices: dict[str, tuple[float, float]] = {}

    async def _refresh_markets_loop(self) -> None:
        while True:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(GAMMA_URL, timeout=10) as resp:
                        markets = await resp.json(content_type=None)
                updated: dict[str, list[str]] = {"BTC": [], "ETH": [], "SOL": [], "XRP": []}
                for m in markets:
                    question = str(m.get("question", "")).lower()
                    if not m.get("active", False):
                        continue
                    if "5" not in question or "min" not in question:
                        continue
                    for asset in updated:
                        if asset.lower() in question:
                            token_ids = m.get("clobTokenIds", [])
                            if isinstance(token_ids, list):
                                updated[asset].extend(str(t) for t in token_ids if t)
                            elif token_ids:
                                updated[asset].append(str(token_ids))
                self._market_map = updated
            except Exception as exc:  # noqa: BLE001
                logger.warning("gamma_refresh_failed", error=str(exc))
            await asyncio.sleep(30)

    async def _subscribe_all(self, ws: websockets.WebSocketClientProtocol) -> None:
        token_ids = {token for ids in self._market_map.values() for token in ids}
        new_ids = token_ids - self._subscribed_tokens
        if not new_ids:
            return
        payload = {"type": "subscribe", "channel": "market", "assets_ids": list(new_ids)}
        await ws.send(json.dumps(payload))
        self._subscribed_tokens.update(new_ids)
        logger.info("polymarket_subscribed", count=len(new_ids))

    def _seconds_remaining(self, end_date: str | None) -> int:
        if not end_date:
            return 0
        try:
            end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
            return max(0, int((end_dt - datetime.now(timezone.utc)).total_seconds()))
        except Exception:
            return 0

    async def _set_connected(self, connected: bool) -> None:
        snap = await self.state.get("feed", default={})
        snap.setdefault("polymarket", {})
        snap["polymarket"].update({"connected": connected, "last_seen": time.time()})
        await self.state.set("feed", value=snap)

    async def run(self) -> None:
        """Run market refresh and websocket consumer indefinitely."""
        asyncio.create_task(self._refresh_markets_loop())

        backoff = 0.2
        while True:
            try:
                async with websockets.connect(WS_URL, ping_interval=20, ping_timeout=20) as ws:
                    await self._set_connected(True)
                    await bus.publish("FEED_RECONNECTED", {"feed": "polymarket"})
                    backoff = 0.2

                    while True:
                        await self._subscribe_all(ws)
                        raw = await asyncio.wait_for(ws.recv(), timeout=1)
                        data = json.loads(raw)
                        asset = str(data.get("asset", "")).upper()
                        if asset not in self._market_map:
                            continue

                        yes_price = float(data.get("yes_price", data.get("price_yes", 0.0)) or 0.0)
                        no_price = float(data.get("no_price", data.get("price_no", 0.0)) or 0.0)
                        spread = abs(yes_price + no_price - 1.0)
                        orderbook = data.get("orderbook", {})

                        latest = await self.state.get("latest_ticks", default={})
                        v30 = float(latest.get(asset, {}).get("velocity_30s", 0.0))
                        sensitivity = 30.0
                        expected_yes = min(0.99, max(0.01, 0.50 + (v30 * 30 * sensitivity)))

                        tick = {
                            "asset": asset,
                            "market_id": str(data.get("market_id", "")),
                            "token_id": str(data.get("token_id", "")),
                            "yes_price": yes_price,
                            "no_price": no_price,
                            "spread": spread,
                            "expected_yes": expected_yes,
                            "lag_score": abs(expected_yes - yes_price),
                            "price_change_since_last_tick": 0.0,
                            "seconds_remaining": self._seconds_remaining(data.get("end_date")),
                            "orderbook": orderbook,
                            "timestamp": time.time(),
                        }
                        poly = await self.state.get("latest_polymarket", default={})
                        poly[asset] = tick
                        await self.state.set("latest_polymarket", value=poly)
                        await bus.publish("POLYMARKET_TICK", tick)

                        prev = self._prev_prices.get(asset)
                        if prev:
                            py, pn = prev
                            crash_mag = max(abs(yes_price - py), abs(no_price - pn))
                            tick["price_change_since_last_tick"] = yes_price - py
                            if crash_mag > 0.15:
                                await bus.publish("PRICE_CRASH", {**tick, "crash_magnitude": crash_mag})
                        self._prev_prices[asset] = (yes_price, no_price)
            except asyncio.TimeoutError:
                continue
            except Exception as exc:  # noqa: BLE001
                await self._set_connected(False)
                await bus.publish("FEED_DISCONNECTED", {"feed": "polymarket", "error": str(exc)})
                logger.warning("polymarket_disconnected", error=str(exc), reconnect_in=backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 5.0)
