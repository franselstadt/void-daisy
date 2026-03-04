"""Risk monitor loop updating degradation level and hard-stop state."""

from __future__ import annotations

import asyncio

from core.event_bus import bus
from core.state import AppState
from risk.degrader import Degrader


class RiskMonitor:
    """Continuously evaluates drawdown and streak risk state."""

    def __init__(self, state: AppState, degrader: Degrader) -> None:
        self.state = state
        self.degrader = degrader

    async def run(self) -> None:
        """Compute level every few seconds and emit events on changes."""
        while True:
            snapshot = await self.state.snapshot()
            bankroll = float(snapshot.get("bankroll", 0.0))
            starting = float(snapshot.get("starting_bankroll", max(bankroll, 1.0)))
            drawdown = max(0.0, (starting - bankroll) / max(starting, 1e-9))
            losses = int(snapshot.get("consecutive_losses", 0))
            win_rate_10 = float(snapshot.get("win_rate_10", 0.5))

            level = self.degrader.evaluate(losses, drawdown, win_rate_10)
            current = int(snapshot.get("degradation_level", 0))
            if level != current:
                await self.state.set("degradation_level", value=level)
                await bus.publish("DEGRADATION_LEVEL_CHANGED", {"old": current, "new": level, "profile": self.degrader.profile(level)})

            if bankroll < 10 and not snapshot.get("bot", {}).get("hard_stopped", False):
                bot = snapshot.get("bot", {})
                bot["hard_stopped"] = True
                await self.state.set("bot", value=bot)
                await bus.publish("DRAWDOWN_CRITICAL", {"bankroll": bankroll, "hard_stop": True})

            await asyncio.sleep(5)
