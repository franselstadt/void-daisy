"""L8 threshold and prime-zone calibrator."""

from __future__ import annotations

import asyncio
from statistics import mean, pstdev

from core.state import state


class L8Calibrator:
    async def run(self) -> None:
        while True:
            wins = list(state.get('stats._entry_elapsed_wins', []))
            if len(wins) >= 10:
                mu = mean(wins)
                sd = pstdev(wins) if len(wins) > 1 else 15
                lo = max(60, int(mu - 1.2 * sd))
                hi = min(240, int(mu + 1.2 * sd))
                state.set_sync('window.prime_zone_start', lo)
                state.set_sync('window.prime_zone_end', hi)
            await asyncio.sleep(300)
