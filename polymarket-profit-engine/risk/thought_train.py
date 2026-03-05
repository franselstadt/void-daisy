"""Loss diagnosis engine that adapts parameters while bot keeps trading."""

from __future__ import annotations

import asyncio
import time

from core.event_bus import bus
from core.state import state


class ThoughtTrain:
    async def run(self) -> None:
        while True:
            losses = int(state.get('stats.consecutive_losses', 0))
            wr10 = float(state.get('stats.win_rate_10', 0.5))
            wr20 = float(state.get('stats.win_rate_20', 0.5))
            trigger = None
            if losses >= 3:
                trigger = '3_CONSECUTIVE_LOSSES'
            elif wr10 < 0.5:
                trigger = 'WR10_DROP'
            elif wr20 < 0.45:
                trigger = 'WR20_DROP'
            if trigger:
                state.set_sync('bot.thought_train_active', True)
                await bus.publish('THOUGHT_TRAIN_TRIGGERED', {'trigger': trigger, 'timestamp': time.time()})
                # conservative adaptations
                cur = float(state.get('trading.min_exhaustion_override', 3.5))
                state.set_sync('trading.min_exhaustion_override', min(6.0, cur + 0.2))
                if losses >= 2:
                    state.set_sync('trading.temp_size_mult', 0.7)
                result = {
                    'timestamp': time.time(),
                    'trigger_reason': trigger,
                    'loss_pattern': 'ENTRY_TOO_EARLY' if losses >= 3 else 'SIGNAL_NOISE',
                    'root_cause': 'Threshold adaptation',
                    'regime_at_time': state.get('bot.current_regime', 'RANGING'),
                    'changes_made': {'trading.min_exhaustion_override': state.get('trading.min_exhaustion_override', 3.5)},
                }
                state.append_list('risk.thought_train.history', result, maxlen=50)
                state.set_sync('risk.thought_train.last', result)
                await bus.publish('THOUGHT_TRAIN_COMPLETED', result)
                state.set_sync('bot.thought_train_active', False)
            await asyncio.sleep(10)
