"""Cross-asset lag strategy engine."""

from __future__ import annotations

import time
from typing import Any

from strategies.base import BaseStrategy


class CrossAssetLagStrategy(BaseStrategy):
    """Trades follower lag between BTC and correlated assets."""

    name = "CROSS_ASSET_LAG"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._btc_move_ts = 0.0
        self._btc_direction = "UP"

    async def on_major_move(self, event: dict[str, Any]) -> None:
        """Track anchor BTC move timestamps."""
        if event.get("asset") != "BTC":
            return
        self._btc_move_ts = float(event.get("timestamp", time.time()))
        self._btc_direction = "UP" if float(event.get("velocity_60s", 0.0)) >= 0 else "DOWN"

    async def evaluate(self, event: dict[str, Any], relax_threshold: bool = False) -> dict[str, Any] | None:
        asset = str(event.get("asset", ""))
        if asset not in {"ETH", "SOL", "XRP"} or self._btc_move_ts <= 0:
            return None
        snapshot = await self.state.snapshot()
        lag_s = float(snapshot.get("correlation_lag", {}).get(asset, 10.0))
        elapsed = time.time() - self._btc_move_ts
        if elapsed > lag_s * 2:
            return None

        tick = snapshot.get("latest_ticks", {}).get(asset, {})
        if (self._btc_direction == "UP" and float(tick.get("velocity_30s", 0.0)) <= 0) or (
            self._btc_direction == "DOWN" and float(tick.get("velocity_30s", 0.0)) >= 0
        ):
            return None
        min_lag = 0.04 if relax_threshold else 0.05
        if float(event.get("lag_score", 0.0)) <= min_lag:
            return None
        if int(event.get("seconds_remaining", 0)) < 80:
            return None

        direction = self._btc_direction
        entry_price = float(event.get("yes_price", 0.5) if direction == "UP" else event.get("no_price", 0.5))
        context = {
            "direction": direction,
            "velocity_10s": tick.get("velocity_10s", 0.0),
            "velocity_30s": tick.get("velocity_30s", 0.0),
            "acceleration": tick.get("acceleration", 0.0),
            "volume_ratio": tick.get("volume_ratio_10_60", 1.0),
            "rsi_14": tick.get("rsi_14", 50.0),
            "spot_price": snapshot.get("latest_spot", {}).get(asset, 0.0),
            "spread": event.get("spread", 0.0),
            "prev_spread": snapshot.get("latest_polymarket", {}).get(asset, {}).get("spread", event.get("spread", 0.0)),
            "orderbook": event.get("orderbook", {}),
            "oracle_lag_seconds": snapshot.get("oracle", {}).get(asset, {}).get("lag_seconds", 0.0),
            "btc_velocity_10s": snapshot.get("latest_ticks", {}).get("BTC", {}).get("velocity_10s", 0.0),
            "cross_asset_divergence": event.get("lag_score", 0.0),
        }
        composed = self.composer.compose(self.name, context)
        min_conf = 0.58 if relax_threshold else 0.65
        if float(composed["confidence"]) < min_conf:
            return None

        return {
            "asset": asset,
            "strategy": self.name,
            "direction": direction,
            "entry_price": entry_price,
            "seconds_remaining": int(event.get("seconds_remaining", 0)),
            "spread": float(event.get("spread", 0.0)),
            **composed,
            "market_id": event.get("market_id", ""),
            "token_id": event.get("token_id", ""),
            "orderbook": event.get("orderbook", {}),
            "oracle_lag_present": bool(context["oracle_lag_seconds"] > 2.0),
            "cross_asset_trade": True,
            "expected_exit_trigger": "LAG_RESOLVED",
            "event_type": "SNIPE_OPPORTUNITY",
        }
