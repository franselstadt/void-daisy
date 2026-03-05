"""Continuous background learner that never pauses trading."""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from core.config import ConfigManager
from core.event_bus import bus
from core.logger import logger
from core.state import AppState
from intelligence.backtester import evaluate_weights
from intelligence.hot_updater import HotUpdater
from learning.signal_optimiser import optimise_weights
from learning.trade_logger import TradeLogger


class ContinuousLearner:
    """Optimises signal weights and deploys on acceptable validation."""

    def __init__(self, state: AppState, config: ConfigManager, trade_logger: TradeLogger) -> None:
        self.state = state
        self.config = config
        self.trade_logger = trade_logger
        self.updater = HotUpdater()
        self._lock = asyncio.Lock()
        self._last_update = 0.0
        self._closed_since_update = 0

    async def on_trade_exited(self, event: dict) -> None:
        self._closed_since_update += 1

    async def _should_run(self) -> tuple[bool, str]:
        now = time.time()
        if now - self._last_update >= 900:
            return True, "time"
        if self._closed_since_update >= 20:
            return True, "volume"
        if int(await self.state.get("consecutive_losses", default=0)) >= 3:
            return True, "defensive"
        if float(await self.state.get("win_rate_10", default=0.5)) < 0.5:
            return True, "performance"
        return False, ""

    def _read_weights(self, path: str | Path = "data/signal_weights.json") -> dict[str, float]:
        try:
            return json.loads(Path(path).read_text())
        except Exception:
            return {}

    async def _run_once(self, trigger: str) -> None:
        if self._lock.locked():
            return
        async with self._lock:
            try:
                trades = await self.trade_logger.fetch_recent_trades(100)
                if len(trades) < 15:
                    return
                old_weights = self._read_weights()
                if not old_weights:
                    return
                new_weights, changes = optimise_weights(trades[:50], old_weights)
                old_wr = evaluate_weights(trades, old_weights)
                new_wr = evaluate_weights(trades, new_weights)
                if new_wr >= old_wr - 0.01:
                    self.updater.deploy_weights(new_weights)
                    await self.trade_logger.log_weight_update(
                        {
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "trigger_reason": trigger,
                            "old_win_rate": old_wr,
                            "new_win_rate": new_wr,
                            "improvement": new_wr - old_wr,
                            "changes": changes,
                        }
                    )
                    await bus.publish("WEIGHTS_UPDATED", {"old_win_rate": old_wr, "new_win_rate": new_wr, "improvement": new_wr - old_wr})
                self._closed_since_update = 0
                self._last_update = time.time()
            except Exception as exc:  # noqa: BLE001
                logger.warning("continuous_learner_error", error=str(exc))

    async def run(self) -> None:
        """Main learner task loop."""
        bus.subscribe("TRADE_EXITED", self.on_trade_exited)
        while True:
            should, trigger = await self._should_run()
            if should:
                await self._run_once(trigger)
            await asyncio.sleep(5)
