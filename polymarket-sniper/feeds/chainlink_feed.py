"""Chainlink stream monitor for lag detection against Binance."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import aiohttp

from core.event_bus import bus
from core.logger import logger
from core.state import AppState

STREAMS = {
    "BTC": "https://data.chain.link/streams/btc-usd",
    "ETH": "https://data.chain.link/streams/eth-usd",
    "SOL": "https://data.chain.link/streams/sol-usd",
    "XRP": "https://data.chain.link/streams/xrp-usd",
}


class ChainlinkFeed:
    """Polling monitor (2s) to estimate oracle lag windows."""

    def __init__(self, state: AppState) -> None:
        self.state = state
        self._last_oracle_ts: dict[str, float] = {}

    async def _parse_price(self, payload: Any) -> float:
        if isinstance(payload, dict):
            for key in ("price", "answer", "value"):
                if key in payload:
                    return float(payload[key])
            for value in payload.values():
                if isinstance(value, (float, int, str)):
                    try:
                        return float(value)
                    except Exception:  # noqa: BLE001
                        continue
        return 0.0

    async def run(self) -> None:
        """Poll feed endpoints and emit lag events."""
        async with aiohttp.ClientSession() as session:
            while True:
                try:
                    for asset, url in STREAMS.items():
                        try:
                            async with session.get(url, timeout=8) as resp:
                                payload = await resp.json(content_type=None)
                            oracle_price = await self._parse_price(payload)
                            spot = float((await self.state.get("latest_spot", default={})).get(asset, 0.0))
                            if spot <= 0 or oracle_price <= 0:
                                continue

                            delta_pct = abs((oracle_price - spot) / spot)
                            lag_seconds = float(payload.get("lag_seconds", payload.get("seconds_since_update", 0.0)) or 0.0)
                            updated = float(payload.get("updated_at", payload.get("timestamp", time.time())) or time.time())
                            if updated > 1e12:
                                updated /= 1000
                            if lag_seconds == 0:
                                lag_seconds = max(0.0, time.time() - updated)
                            direction = "UP" if oracle_price > spot else "DOWN"

                            oracle = await self.state.get("oracle", default={})
                            oracle.setdefault(asset, {})
                            oracle[asset].update(
                                {
                                    "lag_seconds": lag_seconds,
                                    "direction": direction,
                                    "delta_pct": (oracle_price - spot) / spot,
                                    "oracle_price": oracle_price,
                                    "binance_price": spot,
                                    "last_update_timestamp": updated,
                                }
                            )
                            await self.state.set("oracle", value=oracle)

                            update_payload = {
                                "asset": asset,
                                "oracle_price": oracle_price,
                                "binance_price": spot,
                                "lag_seconds": lag_seconds,
                                "delta_pct": delta_pct,
                                "direction": direction,
                            }
                            await bus.publish("CHAINLINK_UPDATE", update_payload)
                            if self._last_oracle_ts.get(asset, 0.0) != updated:
                                self._last_oracle_ts[asset] = updated
                                await bus.publish("ORACLE_UPDATED", update_payload)

                            if lag_seconds > 2.0 and delta_pct > 0.003:
                                await bus.publish(
                                    "ORACLE_LAG_DETECTED",
                                    {**update_payload, "direction": direction, "estimated_window_seconds": lag_seconds},
                                )
                        except Exception as exc:  # noqa: BLE001
                            logger.warning("chainlink_asset_error", asset=asset, error=str(exc))
                    await self.state.set("feed", "chainlink", value={"connected": True, "last_seen": time.time()})
                except Exception as exc:  # noqa: BLE001
                    await self.state.set("feed", "chainlink", value={"connected": False, "last_seen": time.time()})
                    logger.warning("chainlink_loop_error", error=str(exc))
                await asyncio.sleep(2)


async def start_chainlink_feed(state: AppState) -> None:
    """Entrypoint helper for main orchestration."""
    await ChainlinkFeed(state).run()
