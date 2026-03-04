"""Continuous background learning while trading remains live."""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone

from core.config import ConfigManager
from core.event_bus import bus
from core.logger import logger
from core.state import AppState
from learning.backtester import evaluate_win_rate
from learning.hot_updater import HotUpdater
from learning.signal_optimiser import optimise_weights
from learning.trade_logger import TradeLogger


class ContinuousLearner:
    """Runs periodic and trigger-based optimisation without trading downtime."""

    def __init__(self, state: AppState, config: ConfigManager, trade_logger: TradeLogger, updater: HotUpdater) -> None:
        self.state = state
        self.config = config
        self.trade_logger = trade_logger
        self.updater = updater
        self._lock = asyncio.Lock()
        self._last_update = 0.0
        self._completed_since_update = 0

    async def on_trade_exited(self, event: dict) -> None:
        """Count new completed trades for volume trigger."""
        self._completed_since_update += 1

    async def _should_update(self) -> tuple[bool, str]:
        cfg = self.config.get("learning", default={})
        now = time.time()
        if now - self._last_update >= float(cfg.get("update_interval", 300)):
            return True, "time_trigger"
        if self._completed_since_update >= 20:
            return True, "volume_trigger"

        snapshot = await self.state.snapshot()
        if int(snapshot.get("consecutive_losses", 0)) >= 3:
            return True, "defensive_trigger"
        if float(snapshot.get("win_rate_10", 0.5)) < 0.5:
            return True, "performance_trigger"
        return False, ""

    async def _load_weights(self) -> dict[str, float]:
        try:
            return json.loads(self.updater.weight_path.read_text())
        except Exception:
            return {}

    async def _optimise_once(self, trigger_reason: str) -> None:
        if self._lock.locked():
            return
        async with self._lock:
            try:
                recent100 = await self.trade_logger.fetch_recent_trades(100)
                if len(recent100) < int(self.config.get("learning", "min_trades", default=15)):
                    return

                current = await self._load_weights()
                if not current:
                    return

                updated, lifts = optimise_weights(recent100[:50], current)
                old_wr = evaluate_win_rate(recent100, current)
                new_wr = evaluate_win_rate(recent100, updated)
                if new_wr >= old_wr - 0.01:
                    self.updater.deploy(updated)
                    await bus.publish("WEIGHTS_UPDATED", {"old_win_rate": old_wr, "new_win_rate": new_wr, "improvement": new_wr - old_wr})
                    await self.trade_logger.log_weight_update(
                        {
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "trigger_reason": trigger_reason,
                            "old_win_rate": old_wr,
                            "new_win_rate": new_wr,
                            "improvement": new_wr - old_wr,
                            "changes": lifts,
                        }
                    )
                else:
                    logger.warning("learner_rejected_update", old=old_wr, new=new_wr)
                self._last_update = time.time()
                self._completed_since_update = 0
            except Exception as exc:  # noqa: BLE001
                logger.exception("learner_update_error", error=str(exc))

    async def run(self) -> None:
        """Background update loop, independent from trading path."""
        bus.subscribe("TRADE_EXITED", self.on_trade_exited)
        while True:
            should, reason = await self._should_update()
            if should:
                await self._optimise_once(reason)
            await asyncio.sleep(5)
