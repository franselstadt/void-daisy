"""Mean reversion strategy engine."""

from __future__ import annotations

from typing import Any

from strategies.base import BaseStrategy


class MeanReversionStrategy(BaseStrategy):
    """Captures drift back toward fair value in ranging/quiet regimes."""

    name = "MEAN_REVERSION"

    async def evaluate(self, event: dict[str, Any]) -> dict[str, Any] | None:
        yes_price = float(event.get("yes_price", 0.0))
        if not ((0.17 <= yes_price <= 0.35) or (0.65 <= yes_price <= 0.83)):
            return None

        snapshot = await self.state.snapshot()
        regime = str(snapshot.get("bot", {}).get("current_regime", "RANGING"))
        if regime not in {"RANGING", "QUIET"}:
            return None

        asset = str(event.get("asset", ""))
        tick = snapshot.get("latest_ticks", {}).get(asset, {})
        direction = "UP" if yes_price <= 0.35 else "DOWN"
        context = {
            "direction": direction,
            "velocity_10s": tick.get("velocity_10s", 0.0),
            "velocity_30s": tick.get("velocity_30s", 0.0),
            "acceleration": tick.get("acceleration", 0.0),
            "volume_ratio": tick.get("volume_ratio_10_60", 1.0),
            "rsi_14": tick.get("rsi_14", 50.0),
            "spot_price": snapshot.get("latest_spot", {}).get(asset, 0.0),
            "spread": event.get("spread", 1.0),
            "prev_spread": snapshot.get("latest_polymarket", {}).get(asset, {}).get("spread", event.get("spread", 1.0)),
            "orderbook": event.get("orderbook", {}),
            "oracle_lag_seconds": snapshot.get("oracle", {}).get(asset, {}).get("lag_seconds", 0.0),
            "btc_velocity_10s": snapshot.get("latest_ticks", {}).get("BTC", {}).get("velocity_10s", 0.0),
            "cross_asset_divergence": abs(float(event.get("lag_score", 0.0))),
        }
        composed = self.composer.compose(self.name, context)
        if float(composed["confidence"]) < 0.60:
            return None
        if float(event.get("spread", 1.0)) > 0.04:
            return None
        if int(event.get("seconds_remaining", 0)) < 150:
            return None

        entry_price = float(event.get("yes_price", 0.5) if direction == "UP" else event.get("no_price", 0.5))
        return {
            "asset": asset,
            "strategy": self.name,
            "direction": direction,
            "entry_price": entry_price,
            "seconds_remaining": int(event.get("seconds_remaining", 0)),
            "spread": float(event.get("spread", 1.0)),
            **composed,
            "market_id": event.get("market_id", ""),
            "token_id": event.get("token_id", ""),
            "orderbook": event.get("orderbook", {}),
            "oracle_lag_present": bool(context["oracle_lag_seconds"] > 2.0),
            "cross_asset_trade": False,
            "event_type": "SNIPE_OPPORTUNITY",
        }
