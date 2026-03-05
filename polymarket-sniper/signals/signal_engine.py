"""Main signal engine combining filters and weighted confidence."""

from __future__ import annotations

import asyncio
from typing import Any

from core.config import ConfigManager
from core.event_bus import bus
from core.logger import logger
from core.state import AppState
from signals.exhaustion import ExhaustionScorer
from signals.lag_detector import oracle_lag_present
from signals.momentum import alignment_score
from signals.orderbook import imbalance_score


class SignalEngine:
    """Consumes POLYMARKET_TICK and emits SNIPE_OPPORTUNITY."""

    def __init__(self, state: AppState, config: ConfigManager, exhaustion: ExhaustionScorer) -> None:
        self.state = state
        self.config = config
        self.exhaustion = exhaustion

    async def on_polymarket_tick(self, event: dict[str, Any]) -> None:
        """Evaluate all gates and score trade confidence in-memory."""
        try:
            asset = str(event.get("asset", "")).upper()
            if asset not in {"BTC", "ETH", "SOL", "XRP"}:
                return

            yes_price = float(event.get("yes_price", 0.0))
            no_price = float(event.get("no_price", 0.0))
            seconds_remaining = int(event.get("seconds_remaining", 0))
            spread = float(event.get("spread", 1.0))

            asset_cfg = self.config.get("assets", asset, default={})
            trade_cfg = self.config.get("trading", default={})
            entry_min, entry_max = asset_cfg.get("entry_range", [0.06, 0.15])

            direction = "UP" if entry_min <= yes_price <= entry_max else "DOWN" if entry_min <= no_price <= entry_max else ""
            entry_price = yes_price if direction == "UP" else no_price if direction == "DOWN" else 0.0
            if not direction:
                return

            if not (trade_cfg.get("min_seconds", 120) <= seconds_remaining <= trade_cfg.get("max_seconds", 270)):
                return
            if spread > trade_cfg.get("max_spread", 0.04):
                return

            snapshot = await self.state.snapshot()
            if snapshot["bot"]["paused"] or snapshot["bot"]["emergency_stopped"] or snapshot["bot"]["hard_stopped"]:
                return
            if asset in snapshot["open_positions"]:
                return
            if len(snapshot["open_positions"]) >= trade_cfg.get("max_positions", 2):
                return

            latest_tick = snapshot.get("latest_ticks", {}).get(asset, {})
            btc_tick = snapshot.get("latest_ticks", {}).get("BTC", {})
            oracle_lag = float(snapshot.get("oracle", {}).get(asset, {}).get("lag_seconds", 0.0))

            context = {
                "direction": direction,
                "velocity_10s": latest_tick.get("velocity_10s", 0.0),
                "velocity_30s": latest_tick.get("velocity_30s", 0.0),
                "volume_ratio": latest_tick.get("volume_ratio", 1.0),
                "rsi_14": latest_tick.get("rsi_14", 50.0),
                "spot_price": snapshot.get("latest_spot", {}).get(asset, 0.0),
                "spread": spread,
                "prev_spread": snapshot.get("latest_polymarket", {}).get(asset, {}).get("spread", spread),
                "orderbook": event.get("orderbook", {}),
                "btc_velocity_10s": btc_tick.get("velocity_10s", 0.0),
                "oracle_lag_seconds": oracle_lag,
                "consecutive_candles": int(event.get("consecutive_candles", 0)),
                "cross_asset_divergence": float(event.get("cross_asset_divergence", 0.0)),
            }
            exhaustion = self.exhaustion.score(context)

            momentum = alignment_score(direction, float(latest_tick.get("velocity_10s", 0.0)), float(latest_tick.get("velocity_30s", 0.0)))
            lag_component = oracle_lag_present(oracle_lag)
            ob_component = imbalance_score(event.get("orderbook", {}), direction)
            cross_asset_signal = 1.0 if event.get("cross_asset_trade", False) else 0.0

            confidence = (
                (exhaustion["score"] / 10.0) * 0.35
                + momentum * 0.20
                + lag_component * 0.20
                + ob_component * 0.15
                + cross_asset_signal * 0.10
            )
            confidence = max(0.0, min(0.99, confidence))

            ev = (confidence * 0.33) - ((1 - confidence) * entry_price)
            edge_pct = ev / entry_price if entry_price > 0 else -1.0

            if edge_pct < trade_cfg.get("min_edge_pct", 0.15):
                return
            if exhaustion["score"] < trade_cfg.get("min_exhaustion", 3.5):
                return

            opportunity = {
                "asset": asset,
                "direction": direction,
                "entry_price": entry_price,
                "seconds_remaining": seconds_remaining,
                "spread": spread,
                "confidence": confidence,
                "edge_pct": edge_pct,
                "exhaustion_score": exhaustion["score"],
                "signals_fired": exhaustion["signals_fired"],
                "signal_scores": exhaustion["signal_scores"],
                "market_id": event.get("market_id", ""),
                "token_id": event.get("token_id", ""),
                "orderbook": event.get("orderbook", {}),
                "tick": latest_tick,
                "cross_asset_trade": bool(event.get("cross_asset_trade", False)),
                "oracle_lag_present": bool(oracle_lag > 2.0),
            }
            await bus.publish("SNIPE_OPPORTUNITY", opportunity)
        except Exception as exc:  # noqa: BLE001
            logger.exception("signal_engine_error", error=str(exc))

    async def run(self) -> None:
        """Subscribe handler and keep alive."""
        bus.subscribe("POLYMARKET_TICK", self.on_polymarket_tick)
        while True:
            await asyncio.sleep(3600)
