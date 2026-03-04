"""Exhaustion sniper strategy engine."""

from __future__ import annotations

from typing import Any

from strategies.base import BaseStrategy


class ExhaustionSniperStrategy(BaseStrategy):
    """Detects extreme contract pricing for rebound snipes."""

    name = "EXHAUSTION_SNIPER"

    async def evaluate(self, event: dict[str, Any], relax_threshold: bool = False) -> dict[str, Any] | None:
        yes_price = float(event.get("yes_price", 0.0))
        no_price = float(event.get("no_price", 0.0))
        direction = "UP" if 0.04 <= yes_price <= 0.16 else "DOWN" if 0.04 <= no_price <= 0.16 else ""
        if not direction:
            return None

        state = await self.state.snapshot()
        asset = str(event.get("asset", ""))
        tick = state.get("latest_ticks", {}).get(asset, {})
        context = {
            "direction": direction,
            "velocity_10s": tick.get("velocity_10s", 0.0),
            "velocity_30s": tick.get("velocity_30s", 0.0),
            "acceleration": tick.get("acceleration", 0.0),
            "volume_ratio": tick.get("volume_ratio_10_60", tick.get("volume_ratio", 1.0)),
            "rsi_14": tick.get("rsi_14", 50.0),
            "spot_price": state.get("latest_spot", {}).get(asset, 0.0),
            "vwap_deviation": tick.get("vwap_deviation", 0.0),
            "spread": event.get("spread", 1.0),
            "prev_spread": state.get("latest_polymarket", {}).get(asset, {}).get("spread", event.get("spread", 1.0)),
            "orderbook": event.get("orderbook", {}),
            "oracle_lag_seconds": state.get("oracle", {}).get(asset, {}).get("lag_seconds", 0.0),
            "btc_velocity_10s": state.get("latest_ticks", {}).get("BTC", {}).get("velocity_10s", 0.0),
            "btc_acceleration": state.get("latest_ticks", {}).get("BTC", {}).get("acceleration", 0.0),
            "consecutive_candles": tick.get("consecutive_direction", 0),
            "cross_asset_divergence": event.get("cross_asset_divergence", 0.0),
        }
        composed = self.composer.compose(self.name, context)
        entry_price = yes_price if direction == "UP" else no_price
        seconds_remaining = int(event.get("seconds_remaining", 0))

        min_exhaustion = 3.5 * (0.85 if relax_threshold else 1.0)
        min_conf = 0.62 * (0.85 if relax_threshold else 1.0)
        if composed["exhaustion_score"] < min_exhaustion:
            return None
        if float(event.get("spread", 1.0)) > 0.05:
            return None
        if not 100 <= seconds_remaining <= 270:
            return None
        if float(composed["confidence"]) < min_conf:
            return None

        return {
            "asset": asset,
            "strategy": self.name,
            "direction": direction,
            "entry_price": entry_price,
            "seconds_remaining": seconds_remaining,
            "spread": float(event.get("spread", 1.0)),
            **composed,
            "market_id": event.get("market_id", ""),
            "token_id": event.get("token_id", ""),
            "orderbook": event.get("orderbook", {}),
            "oracle_lag_present": bool(context["oracle_lag_seconds"] > 2.0),
            "cross_asset_trade": False,
            "event_type": "SNIPE_OPPORTUNITY",
        }
