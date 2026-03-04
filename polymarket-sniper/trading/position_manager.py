"""Open-position tracking and session metric updates."""

from __future__ import annotations

import asyncio
from typing import Any

from core.event_bus import bus
from core.state import AppState


class PositionManager:
    """State-backed position manager subscribing to trade events."""

    def __init__(self, state: AppState) -> None:
        self.state = state

    async def on_entered(self, event: dict[str, Any]) -> None:
        """Store open position when trade enters."""
        positions = await self.state.get("open_positions", default={})
        positions[event["asset"]] = event
        await self.state.set("open_positions", value=positions)

    async def on_exited(self, event: dict[str, Any]) -> None:
        """Remove position and update performance counters."""
        positions = await self.state.get("open_positions", default={})
        positions.pop(event["asset"], None)
        await self.state.set("open_positions", value=positions)

        bankroll = float(await self.state.get("bankroll", default=0.0)) + float(event.get("net_pnl", 0.0))
        await self.state.set("bankroll", value=round(bankroll, 2))

        last_10 = await self.state.get("metrics", "last_10", default=[])
        won = 1 if float(event.get("net_pnl", 0.0)) > 0 else 0
        last_10.append(won)
        last_10 = last_10[-10:]
        win_rate_10 = sum(last_10) / len(last_10) if last_10 else 0.5
        await self.state.set("metrics", "last_10", value=last_10)
        await self.state.set("win_rate_10", value=win_rate_10)

        cons_losses = int(await self.state.get("consecutive_losses", default=0))
        cons_losses = 0 if won else cons_losses + 1
        await self.state.set("consecutive_losses", value=cons_losses)

    async def run(self) -> None:
        """Subscribe events and stay alive."""
        bus.subscribe("TRADE_ENTERED", self.on_entered)
        bus.subscribe("TRADE_EXITED", self.on_exited)
        while True:
            await asyncio.sleep(3600)
