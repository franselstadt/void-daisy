"""Systematic coverage engine for every 5-minute window."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from core.event_bus import bus
from core.state import state
from plans.engine_manager import EngineManager


@dataclass
class WindowState:
    asset: str
    market_id: str
    opened_at: float
    seconds_elapsed: int
    seconds_remaining: int
    zone_entry_time: float | None = None

    def has_been_in_zone_for(self, seconds: int, zone_min: int, zone_max: int) -> bool:
        in_zone = zone_min <= self.seconds_elapsed <= zone_max
        if in_zone and self.zone_entry_time is None:
            self.zone_entry_time = time.time()
        if not in_zone:
            self.zone_entry_time = None
            return False
        return self.zone_entry_time is not None and (time.time() - self.zone_entry_time) >= seconds


class WindowScheduler:
    WINDOW_DURATION = 300
    OPTIMAL_ENTRY_ZONES = {
        'PLAN_01': (80, 190),
        'PLAN_04': (60, 160),
        'PLAN_02': (0, 240),
        'PLAN_05': (90, 200),
        'PLAN_10': (30, 220),
        'SCHEDULED': (120, 190),
    }

    def __init__(self, engine_manager: EngineManager) -> None:
        self.engine_manager = engine_manager
        self.windows: dict[str, WindowState] = {}
        self.entry_attempted: dict[str, bool] = {'BTC': False, 'ETH': False, 'SOL': False, 'XRP': False}

    async def run(self) -> None:
        while True:
            await self._update_windows()
            await self._check_entries()
            await asyncio.sleep(1)

    async def _update_windows(self) -> None:
        start = int(state.get('window.prime_zone_start', self.OPTIMAL_ENTRY_ZONES['SCHEDULED'][0]))
        end = int(state.get('window.prime_zone_end', self.OPTIMAL_ENTRY_ZONES['SCHEDULED'][1]))
        self.OPTIMAL_ENTRY_ZONES['SCHEDULED'] = (start, end)
        for asset in ['BTC', 'ETH', 'SOL', 'XRP']:
            market_id = str(state.get(f'polymarket.{asset}.market_id', ''))
            if not market_id:
                continue
            remaining = int(state.get(f'polymarket.{asset}.seconds_remaining', 0))
            elapsed = self.WINDOW_DURATION - remaining
            prev = self.windows.get(asset)
            if prev and prev.market_id != market_id:
                self.entry_attempted[asset] = False
                self.windows[asset] = WindowState(asset, market_id, time.time() - elapsed, elapsed, remaining)
                # track window totals
                total = int(state.get(f'coverage.window_total.{asset}', 0)) + 1
                state.set_sync(f'coverage.window_total.{asset}', total)
            elif prev:
                prev.seconds_elapsed = elapsed
                prev.seconds_remaining = remaining
            else:
                self.windows[asset] = WindowState(asset, market_id, time.time() - elapsed, elapsed, remaining)
                total = int(state.get(f'coverage.window_total.{asset}', 0)) + 1
                state.set_sync(f'coverage.window_total.{asset}', total)

    async def _check_entries(self) -> None:
        zmin, zmax = self.OPTIMAL_ENTRY_ZONES['SCHEDULED']
        for asset, w in self.windows.items():
            if self.entry_attempted.get(asset, False):
                continue
            if state.get(f'position.open.{asset}', False):
                continue
            if not (zmin <= w.seconds_elapsed <= zmax):
                continue
            if not w.has_been_in_zone_for(5, zmin, zmax):
                continue

            best = await self._find_best(asset, relax=False)
            trigger = 'WINDOW_SCHEDULER'
            if not best and w.seconds_elapsed >= 200 and w.seconds_remaining >= 80:
                best = await self._find_best(asset, relax=True)
                trigger = 'WINDOW_SCHEDULER_FORCED'

            if best:
                self.entry_attempted[asset] = True
                await bus.publish('SCHEDULED_OPPORTUNITY', {**best, 'trigger': trigger, 'window_elapsed': w.seconds_elapsed, 'window_remaining': w.seconds_remaining})

    async def _find_best(self, asset: str, relax: bool) -> dict | None:
        candidates = self.engine_manager.evaluate_asset(asset, relax_threshold=relax)
        if not candidates:
            return None
        elapsed = int(state.get(f'polymarket.{asset}.window_elapsed', 0))
        best = None
        best_score = -10**9
        for c in candidates:
            zone = self.OPTIMAL_ENTRY_ZONES.get(c.get('plan', ''), self.OPTIMAL_ENTRY_ZONES['SCHEDULED'])
            timing_bonus = 1.08 if zone[0] <= elapsed <= zone[1] else 0.92
            score = float(c.get('ev', 0.0)) * timing_bonus
            c['timing_bonus'] = timing_bonus
            c['ev'] = score
            if score > best_score:
                best_score = score
                best = c
        return best

    def record_attempt(self, asset: str) -> None:
        self.entry_attempted[asset] = True
        state.set_sync(f'coverage.last_attempt.{asset}', time.time())
        covered = int(state.get(f'coverage.window_covered.{asset}', 0)) + 1
        state.set_sync(f'coverage.window_covered.{asset}', covered)
