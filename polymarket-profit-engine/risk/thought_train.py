"""Loss diagnosis engine that adapts parameters while bot keeps trading.

Monitors next 5 trades after intervention to verify fix is working.
Restores temp_size_mult and min_exhaustion_override when performance recovers.
"""

from __future__ import annotations

import asyncio
import time

from core.event_bus import bus
from core.state import state


class ThoughtTrain:
    def __init__(self) -> None:
        self._monitoring_trades = 0
        self._monitoring_start_wr = 0.0

    async def _on_trade_exited(self, event: dict) -> None:
        if self._monitoring_trades <= 0:
            return
        self._monitoring_trades -= 1
        if self._monitoring_trades == 0:
            wr_after = float(state.get('stats.win_rate_10', 0.5))
            if wr_after >= self._monitoring_start_wr:
                cur_mult = float(state.get('trading.temp_size_mult', 1.0))
                state.set_sync('trading.temp_size_mult', min(1.0, cur_mult + 0.1))
                cur_exh = float(state.get('trading.min_exhaustion_override', 3.5))
                state.set_sync('trading.min_exhaustion_override', max(3.5, cur_exh - 0.15))

    async def run(self) -> None:
        bus.subscribe('TRADE_EXITED', self._on_trade_exited)
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
            state.set_sync('trading.temp_size_mult', 0.7)
            await bus.publish('THOUGHT_TRAIN_TRIGGERED', {'trigger': trigger, 'timestamp': time.time()})

            pattern = self._classify_losses()
            changes: dict = {}

            if pattern == 'ENTRY_TOO_EARLY':
                cur = float(state.get('trading.min_exhaustion_override', 3.5))
                new_val = min(6.0, cur + 0.3)
                state.set_sync('trading.min_exhaustion_override', new_val)
                changes['min_exhaustion_override'] = new_val
            elif pattern == 'WRONG_DIRECTION':
                state.set_sync('trading.require_kalman_confirm', True)
                changes['require_kalman_confirm'] = True
            elif pattern == 'STRATEGY_MISMATCH':
                changes['note'] = 'Regime fitness re-evaluation triggered'
            elif pattern == 'SIGNAL_NOISE':
                cur = float(state.get('trading.min_exhaustion_override', 3.5))
                new_val = min(6.0, cur + 0.2)
                state.set_sync('trading.min_exhaustion_override', new_val)
                changes['min_exhaustion_override'] = new_val

            changes['temp_size_mult'] = 0.7

            regime = state.get('bot.current_regime', 'RANGING')
            result = {
                'timestamp': time.time(),
                'trigger_reason': trigger,
                'loss_pattern': pattern,
                'root_cause': f'{pattern} adaptation',
                'regime_at_time': regime,
                'changes_made': changes,
            }
            state.append_list('risk.thought_train.history', result, maxlen=50)
            state.set_sync('risk.thought_train.last', result)
            await bus.publish('THOUGHT_TRAIN_COMPLETED', result)
            state.set_sync('bot.thought_train_active', False)

            self._monitoring_trades = 5
            self._monitoring_start_wr = wr10

            await asyncio.sleep(10)

    def _classify_losses(self) -> str:
        history = list(state.get('risk.thought_train.history', []))
        recent_patterns = [h.get('loss_pattern') for h in history[-3:] if h.get('loss_pattern')]
        if recent_patterns.count('ENTRY_TOO_EARLY') >= 2:
            return 'ENTRY_TOO_EARLY'
        wr10 = float(state.get('stats.win_rate_10', 0.5))
        if wr10 < 0.35:
            return 'STRATEGY_MISMATCH'
        losses = int(state.get('stats.consecutive_losses', 0))
        if losses >= 5:
            return 'WRONG_DIRECTION'
        return 'SIGNAL_NOISE'
