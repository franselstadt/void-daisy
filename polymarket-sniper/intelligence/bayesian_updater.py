"""Bayesian signal belief updater."""

from __future__ import annotations

import asyncio
import json
import time
from math import sqrt
from pathlib import Path
from typing import Any

from core.event_bus import bus
from core.logger import logger
from core.state import AppState
from intelligence.hot_updater import HotUpdater


class BayesianUpdater:
    """Maintains Beta-distribution beliefs per signal."""

    def __init__(self, state: AppState, path: str | Path = "data/bayesian_beliefs.json") -> None:
        self.state = state
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.hot_updater = HotUpdater()
        self.beliefs: dict[str, dict[str, float]] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            self.beliefs = {}
            return
        try:
            self.beliefs = json.loads(self.path.read_text())
        except Exception:  # noqa: BLE001
            self.beliefs = {}

    def _recency_weight(self, timestamp: float) -> float:
        age = time.time() - timestamp
        if age < 600:
            return 4.0
        if age < 1800:
            return 2.5
        if age < 3600:
            return 1.5
        if age < 10800:
            return 1.0
        return 0.5

    def _update_signal(self, signal: str, won: bool, weight: float) -> None:
        row = self.beliefs.setdefault(signal, {"alpha": 1.0, "beta": 1.0, "expected_win_rate": 0.5, "conservative_estimate": 0.5})
        if won:
            row["alpha"] += weight
        else:
            row["beta"] += weight
        alpha = row["alpha"]
        beta = row["beta"]
        expected = alpha / max(1e-9, alpha + beta)
        uncertainty = sqrt(alpha * beta / (((alpha + beta) ** 2) * (alpha + beta + 1)))
        row["expected_win_rate"] = expected
        row["conservative_estimate"] = expected - (0.5 * uncertainty)

    async def on_trade_exited(self, event: dict[str, Any]) -> None:
        """Update beliefs for all fired signals after each trade."""
        won = float(event.get("net_pnl", 0.0)) > 0
        ts = float(event.get("exit_timestamp", time.time()))
        recency = self._recency_weight(ts)
        signals = event.get("signals_fired", list((event.get("signal_scores") or {}).keys()))
        for signal in signals:
            self._update_signal(str(signal), won, recency)
        await self.state.set("bayesian_beliefs", value=self.beliefs)
        await bus.publish("BELIEFS_UPDATED", {"count": len(self.beliefs)})

    async def _persist_loop(self) -> None:
        while True:
            try:
                self.hot_updater.deploy_beliefs(self.beliefs, self.path)
            except Exception as exc:  # noqa: BLE001
                logger.warning("belief_persist_error", error=str(exc))
            await asyncio.sleep(600)

    async def run(self) -> None:
        """Subscribe updates and persist belief state."""
        bus.subscribe("TRADE_EXITED", self.on_trade_exited)
        await self._persist_loop()
