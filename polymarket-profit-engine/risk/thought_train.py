"""Loss diagnosis engine that adapts parameters while bot keeps trading."""

from __future__ import annotations

import asyncio
import time

from core.event_bus import bus
from core.state import state


class ThoughtTrain:
    def __init__(self) -> None:
        self._monitoring_trades = 0
        self._monitoring_start_wr = 0.0

    async def run(self) -> None:
        while True:
            losses = int(state.get('stats.consecutive_losses', 0))
            wr10 = float(state.get('stats.win_rate_10', 0.5))
            wr20 = float(state.get('stats.win_rate_20', 0.5))

            if wr10 >= 0.50 and losses == 0:
                cur_override = float(state.get('trading.min_exhaustion_override', 3.5))
                if cur_override > 3.5:
                    state.set_sync('trading.min_exhaustion_override', max(3.5, cur_override - 0.1))
                cur_mult = float(state.get('trading.temp_size_mult', 1.0))
                if cur_mult < 1.0:
                    state.set_sync('trading.temp_size_mult', min(1.0, cur_mult + 0.05))
                state.set_sync('bot.thought_train_active', False)
                await asyncio.sleep(10)
                continue

            trigger = None
            if losses >= 3:
                trigger = '3_CONSECUTIVE_LOSSES'
            elif wr10 < 0.5:
                trigger = 'WR10_DROP'
            elif wr20 < 0.45:
                trigger = 'WR20_DROP'

            if not trigger:
                await asyncio.sleep(10)
                continue

            state.set_sync('bot.thought_train_active', True)
            await bus.publish('THOUGHT_TRAIN_TRIGGERED', {'trigger': trigger, 'timestamp': time.time()})

            pattern = self._classify_losses()
            changes: dict = {}

            if pattern == 'ENTRY_TOO_EARLY':
                cur = float(state.get('trading.min_exhaustion_override', 3.5))
                new_val = min(6.0, cur + 0.3)
                state.set_sync('trading.min_exhaustion_override', new_val)
                changes['min_exhaustion_override'] = new_val

            elif pattern == 'WRONG_DIRECTION':
                changes['note'] = 'Require kalman_velocity confirmation'

            elif pattern == 'STRATEGY_MISMATCH':
                changes['note'] = 'Regime fitness re-evaluation triggered'

            elif pattern == 'SIGNAL_NOISE':
                cur = float(state.get('trading.min_exhaustion_override', 3.5))
                new_val = min(6.0, cur + 0.2)
                state.set_sync('trading.min_exhaustion_override', new_val)
                changes['min_exhaustion_override'] = new_val

            if losses >= 2:
                state.set_sync('trading.temp_size_mult', 0.7)
                changes['temp_size_mult'] = 0.7

            result = {
                'timestamp': time.time(),
                'trigger_reason': trigger,
                'loss_pattern': pattern,
                'root_cause': f'{pattern} adaptation',
                'regime_at_time': state.get('bot.current_regime', 'RANGING'),
                'changes_made': changes,
            }
            state.append_list('risk.thought_train.history', result, maxlen=50)
            state.set_sync('risk.thought_train.last', result)
            await bus.publish('THOUGHT_TRAIN_COMPLETED', result)
            state.set_sync('bot.thought_train_active', False)

            await asyncio.sleep(10)

    def _classify_losses(self) -> str:
        history = list(state.get('risk.thought_train.history', []))
        recent_patterns = [h.get('loss_pattern') for h in history[-3:] if h.get('loss_pattern')]
        if recent_patterns.count('ENTRY_TOO_EARLY') >= 2:
            return 'ENTRY_TOO_EARLY'

        regime = state.get('bot.current_regime', 'RANGING')
        wr10 = float(state.get('stats.win_rate_10', 0.5))
        if wr10 < 0.35:
            return 'STRATEGY_MISMATCH'

        losses = int(state.get('stats.consecutive_losses', 0))
        if losses >= 5:
            return 'WRONG_DIRECTION'

        return 'SIGNAL_NOISE'
