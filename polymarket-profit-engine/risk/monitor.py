"""Drawdown and exposure monitor."""

from __future__ import annotations

import asyncio
import time

from core.event_bus import bus
from core.state import state
from risk.degrader import assess


class RiskMonitor:
    async def run(self) -> None:
        tick = 0
        while True:
            bankroll = float(state.get('stats.bankroll', state.get('bankroll', 0.0)))
            if state.get('stats.session_start_bankroll') is None:
                state.set_sync('stats.session_start_bankroll', bankroll)
            high = max(float(state.get('stats.high_watermark', bankroll)), bankroll)
            state.set_sync('stats.high_watermark', high)
            dd = max(0.0, (high - bankroll) / max(high, 1e-9))
            state.set_sync('stats.drawdown_pct', dd)
            if dd > 0.15:
                await bus.publish('DRAWDOWN_WARNING', {'drawdown_pct': dd})
            if bankroll < 10 and not state.get('bot.hard_stopped', False):
                state.set_sync('bot.hard_stopped', True)
                await bus.publish('DRAWDOWN_CRITICAL', {'bankroll': bankroll})
            tick += 1
            if tick % 3 == 0:
                old = int(state.get('bot.degradation_level', 0))
                new = assess()
                if old != new:
                    await bus.publish('DEGRADATION_LEVEL_CHANGED', {'old': old, 'new': new})
            await asyncio.sleep(10)
