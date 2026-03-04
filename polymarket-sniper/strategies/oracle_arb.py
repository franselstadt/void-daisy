"""Oracle lag arbitrage strategy engine."""

from __future__ import annotations

from typing import Any

from strategies.base import BaseStrategy


class OracleArbStrategy(BaseStrategy):
    """High-priority event-driven strategy from oracle lag windows."""

    name = "ORACLE_ARB"

    async def evaluate(self, event: dict[str, Any]) -> dict[str, Any] | None:
        if event.get("type") != "ORACLE_LAG_DETECTED":
            return None
        lag = float(event.get("lag_seconds", 0.0))
        delta = abs(float(event.get("delta_pct", 0.0)))
        if lag < 2.0 or lag > 15.0 or delta <= 0.003:
            return None

        snapshot = await self.state.snapshot()
        asset = str(event.get("asset", ""))
        poly = snapshot.get("latest_polymarket", {}).get(asset, {})
        lag_score = float(poly.get("lag_score", 0.0))
        if lag_score <= 0.04:
            return None

        direction = str(event.get("direction", "UP"))
        entry_price = float(poly.get("yes_price", 0.5) if direction == "UP" else poly.get("no_price", 0.5))
        context = {
            "direction": direction,
            "velocity_10s": snapshot.get("latest_ticks", {}).get(asset, {}).get("velocity_10s", 0.0),
            "velocity_30s": snapshot.get("latest_ticks", {}).get(asset, {}).get("velocity_30s", 0.0),
            "acceleration": snapshot.get("latest_ticks", {}).get(asset, {}).get("acceleration", 0.0),
            "volume_ratio": snapshot.get("latest_ticks", {}).get(asset, {}).get("volume_ratio_10_60", 1.0),
            "rsi_14": snapshot.get("latest_ticks", {}).get(asset, {}).get("rsi_14", 50.0),
            "spot_price": snapshot.get("latest_spot", {}).get(asset, 0.0),
            "spread": poly.get("spread", 0.0),
            "prev_spread": poly.get("spread", 0.0),
            "orderbook": poly.get("orderbook", {}),
            "oracle_lag_seconds": lag,
            "btc_velocity_10s": snapshot.get("latest_ticks", {}).get("BTC", {}).get("velocity_10s", 0.0),
        }
        composed = self.composer.compose(self.name, context)
        composed["confidence"] = max(float(composed["confidence"]), 0.72)

        return {
            "asset": asset,
            "strategy": self.name,
            "direction": direction,
            "entry_price": entry_price,
            "seconds_remaining": int(poly.get("seconds_remaining", 0)),
            "spread": float(poly.get("spread", 0.0)),
            **composed,
            "market_id": poly.get("market_id", ""),
            "token_id": poly.get("token_id", ""),
            "orderbook": poly.get("orderbook", {}),
            "oracle_lag_present": True,
            "cross_asset_trade": False,
            "expected_exit_trigger": "ORACLE_UPDATED",
            "event_type": "SNIPE_OPPORTUNITY",
        }
