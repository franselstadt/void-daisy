"""L6 exponential decay correlation tracker."""

from __future__ import annotations

import asyncio

from core.state import state


class L6Correlation:
    async def run(self) -> None:
        while True:
            for asset in ['ETH', 'SOL', 'XRP']:
                lag = float(state.get(f'correlation.lag.{asset}', state.get(f'correlation_state.{asset}', 10.0)))
                state.set_sync(f'learning.l6.correlation.{asset}.lag', lag * 0.995 + lag * 0.005)
            await asyncio.sleep(60)
