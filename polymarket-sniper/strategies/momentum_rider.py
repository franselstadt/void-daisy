"""Momentum rider strategy engine."""

from __future__ import annotations

from typing import Any

from strategies.base import BaseStrategy


class MomentumRiderStrategy(BaseStrategy):
    """Captures sustained directional drift from middle pricing."""

    name = "MOMENTUM_RIDER"

    async def evaluate(self, event: dict[str, Any], relax_threshold: bool = False) -> dict[str, Any] | None:
        yes_price = float(event.get("yes_price", 0.0))
        if not 0.35 <= yes_price <= 0.65:
            return None

        state = await self.state.snapshot()
        asset = str(event.get("asset", ""))
        tick = state.get("latest_ticks", {}).get(asset, {})
        v30 = float(tick.get("velocity_30s", 0.0))
        v60 = float(tick.get("velocity_60s", 0.0))
        direction = "UP" if v30 > 0 else "DOWN"
        if abs(v30) < 0.0004 or abs(v60) < 0.0002:
            return None

        context = {
            "direction": direction,
            "velocity_10s": tick.get("velocity_10s", 0.0),
            "velocity_30s": v30,
            "acceleration": tick.get("acceleration", 0.0),
            "volume_ratio": tick.get("volume_ratio_10_60", 1.0),
            "rsi_14": tick.get("rsi_14", 50.0),
            "spot_price": state.get("latest_spot", {}).get(asset, 0.0),
            "vwap_deviation": tick.get("vwap_deviation", 0.0),
            "spread": event.get("spread", 1.0),
            "prev_spread": state.get("latest_polymarket", {}).get(asset, {}).get("spread", event.get("spread", 1.0)),
            "orderbook": event.get("orderbook", {}),
            "oracle_lag_seconds": state.get("oracle", {}).get(asset, {}).get("lag_seconds", 0.0),
            "btc_velocity_10s": state.get("latest_ticks", {}).get("BTC", {}).get("velocity_10s", 0.0),
            "consecutive_candles": tick.get("consecutive_direction", 0),
            "cross_asset_divergence": event.get("cross_asset_divergence", 0.0),
        }
        composed = self.composer.compose(self.name, context)
        signals = 0
        signals += int(abs(v30) > 0.0005)
        signals += int((v30 > 0 and v60 > 0) or (v30 < 0 and v60 < 0))
        signals += int((v30 > 0 and float(tick.get("acceleration", 0.0)) > 0) or (v30 < 0 and float(tick.get("acceleration", 0.0)) < 0))
        signals += int(float(tick.get("volume_ratio_10_60", 1.0)) > 1.2)
        signals += int(float(event.get("lag_score", 0.0)) > 0.04)

        min_signals = 4 if relax_threshold else 5
        min_conf = 0.58 if relax_threshold else 0.68
        if signals < min_signals:
            return None
        if float(composed["confidence"]) < min_conf:
            return None
        if int(event.get("seconds_remaining", 0)) < 150:
            return None
        if float(event.get("spread", 1.0)) > 0.04:
            return None

        entry_price = yes_price if direction == "UP" else float(event.get("no_price", 1.0 - yes_price))
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
