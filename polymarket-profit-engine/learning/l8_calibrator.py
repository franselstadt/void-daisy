"""L8 adaptive threshold calibrator.

Calibrates per-plan thresholds and handles thought train recommendations.
Runs every 3600s (config learning.l8_optimize_every_secs).
"""

from __future__ import annotations

import asyncio
from statistics import mean, pstdev

from core.config import config
from core.state import state


class L8Calibrator:
    def __init__(self) -> None:
        self._pending_tt: list[dict] = []

    async def on_thought_train(self, event: dict) -> None:
        self._pending_tt.append(event)

    def _calibrate_prime_zone(self) -> None:
        wins = list(state.get('stats._entry_elapsed_wins', []))
        if len(wins) < 10:
            return
        mu = mean(wins)
        sd = pstdev(wins) if len(wins) > 1 else 15
        lo = max(60, int(mu - 1.2 * sd))
        hi = min(240, int(mu + 1.2 * sd))
        state.set_sync('window.prime_zone_start', lo)
        state.set_sync('window.prime_zone_end', hi)

    def _calibrate_plan_thresholds(self) -> None:
        for i in range(1, 13):
            plan = f'PLAN_{i:02d}'
            wr = float(state.get(f'stats.win_rate_20.{plan}', 0.5))
            plan_cfg = config.get('plans', plan, default={}) or {}
            if not isinstance(plan_cfg, dict):
                continue

            base_conf = float(plan_cfg.get('min_confidence', 0.62))
            base_exh = float(plan_cfg.get('min_exhaustion', 3.5))

            if wr > 0.65:
                state.set_sync(f'learning.l8.thresholds.{plan}.min_confidence', max(0.50, base_conf - 0.03))
                state.set_sync(f'learning.l8.thresholds.{plan}.min_exhaustion', max(2.5, base_exh - 0.3))
            elif wr < 0.45:
                state.set_sync(f'learning.l8.thresholds.{plan}.min_confidence', min(0.85, base_conf + 0.05))
                state.set_sync(f'learning.l8.thresholds.{plan}.min_exhaustion', min(6.0, base_exh + 0.5))

    def _apply_thought_train_recommendations(self) -> None:
        for tt in self._pending_tt:
            pattern = tt.get('loss_pattern', '')
            if pattern == 'ENTRY_TOO_EARLY':
                cur = float(state.get('trading.min_exhaustion_override', 3.5))
                state.set_sync('trading.min_exhaustion_override', min(6.0, cur + 0.3))
            elif pattern == 'SIGNAL_NOISE':
                cur_conf = float(config.get('trading', 'min_confidence', default=0.62))
                state.set_sync('trading.min_confidence_override', min(0.80, cur_conf + 0.04))
            elif pattern == 'STRATEGY_MISMATCH':
                regime = tt.get('regime_at_time', 'RANGING')
                state.set_sync(f'learning.l8.regime_penalty.{regime}', 0.8)
        self._pending_tt.clear()

    async def run(self) -> None:
        interval = int(config.get('learning', 'l8_optimize_every_secs', default=3600))
        while True:
            self._calibrate_prime_zone()
            self._calibrate_plan_thresholds()
            self._apply_thought_train_recommendations()
            await asyncio.sleep(interval)
