"""L2 Kalman smoother for price/velocity.

State equation:  x(t) = F * x(t-1) + w     where w ~ N(0, Q)
Measurement:     z(t) = H * x(t) + v        where v ~ N(0, R)

State vector x = [price, velocity]^T
F = [[1, dt], [0, 1]]
H = [1, 0]
Q = process_noise * I
R = measurement_noise (scalar)
"""

from __future__ import annotations

import asyncio
import time

import numpy as np

from core.config import config
from core.state import state


class L2Kalman:
    def __init__(self) -> None:
        self.process_noise = float(config.get('learning', 'l2_process_noise', default=0.001))
        self.measurement_noise = float(config.get('learning', 'l2_measurement_noise', default=0.1))
        self._filters: dict[str, dict] = {}

    def _init_filter(self, asset: str, price: float) -> dict:
        return {
            'x': np.array([price, 0.0]),
            'P': np.eye(2) * 1.0,
            'last_t': time.time(),
        }

    def _predict_update(self, f: dict, z_price: float, now: float) -> tuple[float, float]:
        dt = max(0.01, now - f['last_t'])
        f['last_t'] = now

        F = np.array([[1.0, dt], [0.0, 1.0]])
        H = np.array([[1.0, 0.0]])
        Q = self.process_noise * np.array([[dt**3 / 3, dt**2 / 2], [dt**2 / 2, dt]])
        R = np.array([[self.measurement_noise]])

        x_pred = F @ f['x']
        P_pred = F @ f['P'] @ F.T + Q

        z = np.array([z_price])
        y = z - H @ x_pred
        S = H @ P_pred @ H.T + R
        K = P_pred @ H.T @ np.linalg.inv(S)

        f['x'] = x_pred + (K @ y).flatten()
        f['P'] = (np.eye(2) - K @ H) @ P_pred

        return float(f['x'][0]), float(f['x'][1])

    async def on_tick(self, event: dict) -> None:
        a = event['asset']
        p = float(event['price'])
        now = float(event.get('timestamp', time.time()))

        if a not in self._filters:
            self._filters[a] = self._init_filter(a, p)

        kalman_price, kalman_velocity = self._predict_update(self._filters[a], p, now)

        state.set_sync(f'learning.l2.kalman.{a}.x_price', kalman_price)
        state.set_sync(f'learning.l2.kalman.{a}.x_velocity', kalman_velocity)
        state.set_sync(f'price.{a}.kalman_price', kalman_price)
        state.set_sync(f'price.{a}.kalman_velocity', kalman_velocity)

    async def run(self) -> None:
        while True:
            await asyncio.sleep(3600)
