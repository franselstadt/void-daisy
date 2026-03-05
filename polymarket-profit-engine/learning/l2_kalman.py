"""L2 Kalman smoother for price/velocity."""

from __future__ import annotations

import asyncio

from core.event_bus import bus
from core.state import state


class L2Kalman:
    async def on_tick(self, event: dict) -> None:
        a = event['asset']
        p = float(event['price'])
        prev = float(state.get(f'learning.l2.kalman.{a}.x_price', p))
        prev_v = float(state.get(f'learning.l2.kalman.{a}.x_velocity', 0.0))
        x = prev * 0.8 + p * 0.2
        v = prev_v * 0.8 + float(event.get('velocity_10s', 0.0)) * 0.2
        state.set_sync(f'learning.l2.kalman.{a}.x_price', x)
        state.set_sync(f'learning.l2.kalman.{a}.x_velocity', v)
        state.set_sync(f'price.{a}.kalman_price', x)
        state.set_sync(f'price.{a}.kalman_velocity', v)

    async def run(self) -> None:
        bus.subscribe('PRICE_TICK', self.on_tick)
        while True:
            await asyncio.sleep(3600)
