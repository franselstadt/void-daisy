"""Pre-trade guardrails."""

from __future__ import annotations

from typing import Any

from core.config import ConfigManager
from core.state import AppState


class TradeGuardian:
    """Validates whether a trade can be executed right now."""

    def __init__(self, state: AppState, config: ConfigManager) -> None:
        self.state = state
        self.config = config

    async def check(self, opportunity: dict[str, Any], thresholds: dict[str, float]) -> tuple[bool, str]:
        """Return trade allow/deny and reason."""
        snapshot = await self.state.snapshot()
        bot = snapshot["bot"]
        trade_cfg = self.config.get("trading", default={})

        if bot["emergency_stopped"]:
            return False, "emergency_stopped"
        if bot["hard_stopped"]:
            return False, "hard_stopped"
        if bot["paused"]:
            return False, "paused"
        if snapshot.get("bankroll", 0.0) < 10:
            return False, "bankroll_critical"

        open_positions = snapshot.get("open_positions", {})
        if len(open_positions) >= trade_cfg.get("max_positions", 2):
            return False, "max_positions"
        if opportunity["asset"] in open_positions:
            return False, "asset_already_open"

        current_exposure = sum(float(p.get("bet_size", 0.0)) for p in open_positions.values())
        if current_exposure + float(opportunity.get("bet_size", 0.0)) > snapshot.get("bankroll", 0.0) * 0.25:
            return False, "exposure_limit"

        min_edge = trade_cfg.get("min_edge_pct", 0.15) + thresholds.get("confidence_bonus", 0.0)
        min_exhaustion = trade_cfg.get("min_exhaustion", 3.5) + thresholds.get("exhaustion_bonus", 0.0)
        if float(opportunity.get("edge_pct", 0.0)) < min_edge:
            return False, "edge_too_low"
        if float(opportunity.get("exhaustion_score", 0.0)) < min_exhaustion:
            return False, "exhaustion_too_low"

        s = int(opportunity.get("seconds_remaining", 0))
        if s < trade_cfg.get("min_seconds", 120) or s > trade_cfg.get("max_seconds", 270):
            return False, "time_window"
        if float(opportunity.get("spread", 1.0)) > trade_cfg.get("max_spread", 0.04):
            return False, "spread_too_wide"

        if opportunity["asset"] == "XRP" and snapshot.get("xrp", {}).get("news_blackout_active", False):
            return False, "xrp_blackout"

        latest = snapshot.get("latest_ticks", {})
        major_all = all(abs(float(latest.get(a, {}).get("pct_change_60s", 0.0))) > 0.003 for a in ("BTC", "ETH", "SOL", "XRP"))
        if major_all:
            return False, "macro_event"

        return True, "allowed"
