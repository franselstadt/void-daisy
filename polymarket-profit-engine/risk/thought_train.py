"""Loss diagnosis engine that adapts parameters while bot keeps trading."""

from __future__ import annotations

import asyncio
import time

from core.event_bus import bus
from core.state import state

PATTERNS = ['ENTRY_TOO_EARLY', 'WRONG_DIRECTION', 'STRATEGY_MISMATCH', 'SIGNAL_NOISE']


class ThoughtTrain:
    def __init__(self) -> None:
        self._monitoring_trades: int = 0
        self._monitoring_target: int = 5
        self._monitoring_start_wr: float = 0.0
        self._monitoring_wins: int = 0

    async def on_trade_exit(self, event: dict) -> None:
        if self._monitoring_trades > 0:
            self._monitoring_trades -= 1
            if int(event.get('won', 0)) == 1:
                self._monitoring_wins += 1

            if self._monitoring_trades == 0:
                post_wr = self._monitoring_wins / self._monitoring_target
                improved = post_wr > self._monitoring_start_wr
                state.set_sync('risk.thought_train.monitoring_result', {
                    'pre_wr': self._monitoring_start_wr,
                    'post_wr': post_wr,
                    'improved': improved,
                })
                if improved:
                    cur_mult = float(state.get('trading.temp_size_mult', 1.0))
                    state.set_sync('trading.temp_size_mult', min(1.0, cur_mult + 0.1))
                    cur_exh = float(state.get('trading.min_exhaustion_override', 3.5))
                    state.set_sync('trading.min_exhaustion_override', max(3.5, cur_exh - 0.15))

    async def run(self) -> None:
        bus.subscribe('TRADE_EXITED', self.on_trade_exit)
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
            regime = str(state.get('bot.current_regime', 'RANGING'))

            if pattern == 'ENTRY_TOO_EARLY':
                cur = float(state.get('trading.min_exhaustion_override', 3.5))
                new_val = min(6.0, cur + 0.3)
                state.set_sync('trading.min_exhaustion_override', new_val)
                changes['min_exhaustion_override'] = new_val

            elif pattern == 'WRONG_DIRECTION':
                state.set_sync('trading.require_kalman_confirm', True)
                changes['require_kalman_confirm'] = True
                if regime in ('TRENDING_UP', 'TRENDING_DOWN'):
                    state.set_sync('trading.trend_only_mode', True)
                    changes['trend_only_mode'] = True

            elif pattern == 'STRATEGY_MISMATCH':
                changes['note'] = f'Regime {regime} fitness re-evaluation triggered'
                for i in range(1, 13):
                    plan = f'PLAN_{i:02d}'
                    plan_wr = sum(state.get(f'stats._plan_last10.{plan}', [])) / max(1, len(state.get(f'stats._plan_last10.{plan}', [])))
                    if plan_wr < 0.3:
                        state.set_sync(f'plan.{plan}.regime_disabled.{regime}', True)
                        changes[f'{plan}_disabled_for_{regime}'] = True

            elif pattern == 'SIGNAL_NOISE':
                cur = float(state.get('trading.min_exhaustion_override', 3.5))
                new_val = min(6.0, cur + 0.2)
                state.set_sync('trading.min_exhaustion_override', new_val)
                changes['min_exhaustion_override'] = new_val

            if losses >= 2:
                state.set_sync('trading.temp_size_mult', 0.7)
                changes['temp_size_mult'] = 0.7

            self._monitoring_trades = self._monitoring_target
            self._monitoring_start_wr = wr10
            self._monitoring_wins = 0

            result = {
                'timestamp': time.time(),
                'trigger_reason': trigger,
                'loss_pattern': pattern,
                'root_cause': f'{pattern} adaptation',
                'regime_at_time': regime,
                'changes_made': changes,
                'monitoring_next_trades': self._monitoring_target,
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
