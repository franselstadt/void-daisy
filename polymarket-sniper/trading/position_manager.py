"""Open-position tracking and session metric updates."""

from __future__ import annotations

import asyncio
import uuid
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
        trade = dict(event)
        trade.setdefault("position_id", str(uuid.uuid4()))
        trade.setdefault("high_watermark_price", float(trade.get("entry_price", 0.0)))
        positions[event["asset"]] = trade
        await self.state.set("open_positions", value=positions)
        exposure = float(await self.state.get("stats", "open_exposure", default=0.0)) + float(event.get("bet_size", 0.0))
        await self.state.set("stats", "open_exposure", value=round(exposure, 4))

    async def on_exited(self, event: dict[str, Any]) -> None:
        """Remove position and update performance counters."""
        positions = await self.state.get("open_positions", default={})
        positions.pop(event["asset"], None)
        await self.state.set("open_positions", value=positions)
        exposure = max(0.0, float(await self.state.get("stats", "open_exposure", default=0.0)) - float(event.get("bet_size", 0.0)))
        await self.state.set("stats", "open_exposure", value=round(exposure, 4))

        bankroll = float(await self.state.get("bankroll", default=0.0)) + float(event.get("net_pnl", 0.0))
        await self.state.set("bankroll", value=round(bankroll, 2))

        last_10 = await self.state.get("metrics", "last_10", default=[])
        last_20 = await self.state.get("metrics", "last_20", default=[])
        won = 1 if float(event.get("net_pnl", 0.0)) > 0 else 0
        last_10.append(won)
        last_20.append(won)
        last_10 = last_10[-10:]
        last_20 = last_20[-20:]
        win_rate_10 = sum(last_10) / len(last_10) if last_10 else 0.5
        win_rate_20 = sum(last_20) / len(last_20) if last_20 else 0.5
        await self.state.set("metrics", "last_10", value=last_10)
        await self.state.set("metrics", "last_20", value=last_20)
        await self.state.set("win_rate_10", value=win_rate_10)
        await self.state.set("win_rate_20", value=win_rate_20)

        strategy = str(event.get("strategy", "EXHAUSTION_SNIPER"))
        wr10s = await self.state.get("stats", "win_rate_10", default={})
        wr20s = await self.state.get("stats", "win_rate_20", default={})
        seq10 = wr10s.get(f"{strategy}_seq", [])
        seq20 = wr20s.get(f"{strategy}_seq", [])
        seq10.append(won)
        seq20.append(won)
        wr10s[f"{strategy}_seq"] = seq10[-10:]
        wr20s[f"{strategy}_seq"] = seq20[-20:]
        wr10s[strategy] = sum(wr10s[f"{strategy}_seq"]) / max(1, len(wr10s[f"{strategy}_seq"]))
        wr20s[strategy] = sum(wr20s[f"{strategy}_seq"]) / max(1, len(wr20s[f"{strategy}_seq"]))
        await self.state.set("stats", "win_rate_10", value=wr10s)
        await self.state.set("stats", "win_rate_20", value=wr20s)

        cons_losses = int(await self.state.get("consecutive_losses", default=0))
        cons_losses = 0 if won else cons_losses + 1
        await self.state.set("consecutive_losses", value=cons_losses)

    async def run(self) -> None:
        """Subscribe events and stay alive."""
        bus.subscribe("TRADE_ENTERED", self.on_entered)
        bus.subscribe("TRADE_EXITED", self.on_exited)
        while True:
            await asyncio.sleep(3600)
