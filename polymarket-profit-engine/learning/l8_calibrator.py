"""L8 threshold and prime-zone calibrator.

Runs every 3600s. Calibrates:
  - Window prime-zone boundaries from winning entry timestamps
  - Per-plan confidence and exhaustion thresholds
  - Applies thought train recommendations
"""

from __future__ import annotations

import asyncio
from statistics import mean, pstdev

from core.event_bus import bus
from core.state import state


class L8Calibrator:
    def __init__(self) -> None:
        self._pending_recommendations: list[dict] = []

    async def on_thought_train(self, event: dict) -> None:
        self._pending_recommendations.append(event)

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
            seq = list(state.get(f'stats._plan_last10.{plan}', []))
            if len(seq) < 5:
                continue
            wr = sum(seq) / len(seq) if seq else 0.5

            cur_conf = float(state.get(f'calibration.{plan}.min_confidence', 0.62))
            cur_exh = float(state.get(f'calibration.{plan}.min_exhaustion', 3.5))

            if wr > 0.70:
                new_conf = max(0.55, cur_conf - 0.01)
                new_exh = max(3.0, cur_exh - 0.1)
            elif wr < 0.45:
                new_conf = min(0.85, cur_conf + 0.02)
                new_exh = min(6.0, cur_exh + 0.2)
            else:
                new_conf = cur_conf
                new_exh = cur_exh

            state.set_sync(f'calibration.{plan}.min_confidence', round(new_conf, 4))
            state.set_sync(f'calibration.{plan}.min_exhaustion', round(new_exh, 2))

    def _apply_thought_train_recommendations(self) -> None:
        while self._pending_recommendations:
            rec = self._pending_recommendations.pop(0)
            pattern = rec.get('loss_pattern', '')
            changes = rec.get('changes_made', {})

            if pattern == 'ENTRY_TOO_EARLY':
                for i in range(1, 13):
                    plan = f'PLAN_{i:02d}'
                    cur = float(state.get(f'calibration.{plan}.min_exhaustion', 3.5))
                    state.set_sync(f'calibration.{plan}.min_exhaustion', min(6.0, cur + 0.15))

            elif pattern == 'STRATEGY_MISMATCH':
                regime = rec.get('regime_at_time', 'RANGING')
                for i in range(1, 13):
                    plan = f'PLAN_{i:02d}'
                    wr = sum(state.get(f'stats._plan_last10.{plan}', [])) / max(1, len(state.get(f'stats._plan_last10.{plan}', [])))
                    if wr < 0.3:
                        state.set_sync(f'calibration.{plan}.regime_penalty.{regime}', 0.5)

            elif pattern == 'SIGNAL_NOISE':
                for i in range(1, 13):
                    plan = f'PLAN_{i:02d}'
                    cur = float(state.get(f'calibration.{plan}.min_confidence', 0.62))
                    state.set_sync(f'calibration.{plan}.min_confidence', min(0.85, cur + 0.01))

    async def run(self) -> None:
        while True:
            self._calibrate_prime_zone()
            self._calibrate_plan_thresholds()
            self._apply_thought_train_recommendations()
            await asyncio.sleep(3600)
