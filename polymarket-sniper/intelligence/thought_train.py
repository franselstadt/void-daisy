"""Loss diagnosis and adaptive parameter tuning engine."""

from __future__ import annotations

import asyncio
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from core.config import ConfigManager
from core.event_bus import bus
from core.logger import logger
from core.state import AppState
from learning.trade_logger import TradeLogger


class ThoughtTrain:
    """Runs targeted diagnostics after loss streaks without halting trading."""

    def __init__(self, state: AppState, config: ConfigManager, trade_logger: TradeLogger) -> None:
        self.state = state
        self.config = config
        self.trade_logger = trade_logger
        self._lock = asyncio.Lock()

    def _classify_loss(self, trade: dict[str, Any]) -> str:
        if int(trade.get("seconds_remaining_at_entry", 999)) < 130:
            return "ENTRY_TOO_LATE"
        if float(trade.get("exhaustion_score", 0.0)) < 4.0:
            return "ENTRY_TOO_EARLY"
        if float(trade.get("pnl_pct", 0.0)) < -0.4:
            return "WRONG_DIRECTION"
        return "SIGNAL_NOISE"

    async def _need_run(self) -> tuple[bool, str]:
        cons = int(await self.state.get("consecutive_losses", default=0))
        wr10 = float(await self.state.get("win_rate_10", default=0.5))
        wr20 = float(await self.state.get("win_rate_20", default=0.5))
        if cons >= 3:
            return True, "3_consecutive_losses"
        if wr10 < 0.50:
            return True, "win_rate_10_drop"
        if wr20 < 0.45:
            return True, "win_rate_20_drop"
        return False, ""

    async def _deploy_fix(self, dominant: str) -> dict[str, Any]:
        changes: dict[str, Any] = {}
        trading = dict(self.config.get("trading", default={}))
        if dominant == "ENTRY_TOO_EARLY":
            trading["min_exhaustion"] = round(float(trading.get("min_exhaustion", 3.5)) + 0.4, 2)
            changes["trading.min_exhaustion"] = trading["min_exhaustion"]
        elif dominant == "ENTRY_TOO_LATE":
            trading["min_seconds"] = max(100, int(trading.get("min_seconds", 100)) + 20)
            changes["trading.min_seconds"] = trading["min_seconds"]
        elif dominant == "WRONG_DIRECTION":
            trading["min_edge_pct"] = round(float(trading.get("min_edge_pct", 0.08)) + 0.02, 3)
            changes["trading.min_edge_pct"] = trading["min_edge_pct"]
        else:
            trading["max_spread"] = round(max(0.03, float(trading.get("max_spread", 0.05)) - 0.005), 3)
            changes["trading.max_spread"] = trading["max_spread"]
        self.config.update({"trading": trading})
        return changes

    async def _run_once(self, trigger: str) -> None:
        if self._lock.locked():
            return
        async with self._lock:
            try:
                await bus.publish("THOUGHT_TRAIN_TRIGGERED", {"trigger": trigger})
                bot = await self.state.get("bot", default={})
                bot["thought_train_active"] = True
                await self.state.set("bot", value=bot)

                recent = await self.trade_logger.fetch_recent_trades(20)
                losses = [t for t in recent if int(t.get("won", 1)) == 0][:10]
                patterns = Counter(self._classify_loss(t) for t in losses) or Counter({"SIGNAL_NOISE": 1})
                dominant = patterns.most_common(1)[0][0]
                changes = await self._deploy_fix(dominant)

                result = {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "trigger_reason": trigger,
                    "loss_pattern": dominant,
                    "root_cause": f"Dominant pattern detected: {dominant}",
                    "regime_at_time": await self.state.get("bot", "current_regime", default="RANGING"),
                    "changes_made": changes,
                }
                history = await self.state.get("thought_train", "history", default=[])
                history.append(result)
                await self.state.set("thought_train", value={"history": history[-20:], "last_result": result})
                await bus.publish("THOUGHT_TRAIN_COMPLETED", result)
            except Exception as exc:  # noqa: BLE001
                logger.warning("thought_train_error", error=str(exc))
            finally:
                bot = await self.state.get("bot", default={})
                bot["thought_train_active"] = False
                await self.state.set("bot", value=bot)

    async def run(self) -> None:
        """Monitor conditions and launch diagnostics conservatively."""
        while True:
            should, trigger = await self._need_run()
            if should:
                await self._run_once(trigger)
            await asyncio.sleep(10)
