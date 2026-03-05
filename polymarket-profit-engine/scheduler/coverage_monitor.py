"""6-minute coverage monitor and diagnostics."""

from __future__ import annotations

import asyncio
import time

from core.event_bus import bus
from core.logger import logger
from core.state import state


class CoverageMonitor:
    COVERAGE_WINDOW_SECONDS = 360

    async def run(self) -> None:
        while True:
            await self._check()
            await asyncio.sleep(60)

    async def _check(self) -> None:
        now = time.time()
        for asset in ['BTC', 'ETH', 'SOL', 'XRP']:
            last = float(state.get(f'coverage.last_attempt.{asset}', 0.0))
            gap = now - last if last > 0 else 99999
            misses = int(state.get(f'coverage.misses.{asset}', 0))
            if gap <= self.COVERAGE_WINDOW_SECONDS:
                if misses:
                    state.set_sync(f'coverage.misses.{asset}', 0)
                state.set_sync(f'coverage.threshold_relax.{asset}', 1.0)
                continue

            misses += 1
            state.set_sync(f'coverage.misses.{asset}', misses)
            logger.warning('coverage_gap', asset=asset, gap_minutes=round(gap/60, 2), misses=misses)

            if misses == 1:
                state.set_sync(f'coverage.threshold_relax.{asset}', 0.90)
            elif misses == 2:
                state.set_sync(f'coverage.threshold_relax.{asset}', 0.80)
                await bus.publish('COVERAGE_ALERT', {'asset': asset, 'gap_minutes': gap / 60, 'misses': misses})
            else:
                reasons = []
                if not state.get(f'feed.binance.{asset}.connected', False):
                    reasons.append('BINANCE_FEED_DOWN')
                if not state.get('feed.polymarket.connected', False):
                    reasons.append('POLYMARKET_FEED_DOWN')
                if asset == 'XRP' and state.get('xrp.news_blackout_active', False):
                    reasons.append('NEWS_BLACKOUT_ACTIVE')
                reasons.append(f"REGIME:{state.get('bot.current_regime', 'RANGING')}")
                reasons.append(f"DEGRADATION:{state.get('bot.degradation_level', 0)}")
                await bus.publish('COVERAGE_FAILURE', {'asset': asset, 'gap_minutes': gap / 60, 'reasons': reasons})
