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
        tick = 0
        while True:
            snapshot = await self.state.snapshot()
            bankroll = float(snapshot.get("bankroll", 0.0))
            high_watermark = max(float(snapshot.get("high_watermark_bankroll", bankroll)), bankroll)
            await self.state.set("high_watermark_bankroll", value=high_watermark)
            drawdown = max(0.0, (high_watermark - bankroll) / max(high_watermark, 1e-9))
            losses = int(snapshot.get("consecutive_losses", 0))
            win_rate_10 = float(snapshot.get("win_rate_10", 0.5))
            if drawdown > 0.15:
                await bus.publish("DRAWDOWN_WARNING", {"drawdown_pct": drawdown})

            tick += 1
            if tick % 6 == 0:
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

            await asyncio.sleep(10)
