"""L2 Kalman filter price/velocity tracker.

Two-state model: [price, velocity]
State equation:  x(t) = F*x(t-1) + w  (process noise)
Measurement:     z(t) = H*x(t) + v    (measurement noise)
F = [[1, dt], [0, 1]]  (constant velocity model)
H = [1, 0]              (observe price only)
"""

from __future__ import annotations

import asyncio
import time

import numpy as np

from core.config import config
from core.state import state


class _AssetFilter:
    def __init__(self, q: float, r: float) -> None:
        self.x = np.array([0.0, 0.0])
        self.P = np.eye(2) * 1000.0
        self.Q_base = q
        self.R = r
        self.last_t = 0.0
        self.initialized = False

    def update(self, price: float, ts: float) -> tuple[float, float]:
        if not self.initialized:
            self.x = np.array([price, 0.0])
            self.P = np.eye(2) * 1.0
            self.last_t = ts
            self.initialized = True
            return price, 0.0

        dt = max(0.001, ts - self.last_t)
        self.last_t = ts

        F = np.array([[1.0, dt], [0.0, 1.0]])
        H = np.array([[1.0, 0.0]])
        Q = np.array([[self.Q_base * dt, 0.0], [0.0, self.Q_base * dt]])
        R = np.array([[self.R]])

        x_pred = F @ self.x
        P_pred = F @ self.P @ F.T + Q

        y = np.array([price]) - H @ x_pred
        S = H @ P_pred @ H.T + R
        K = P_pred @ H.T @ np.linalg.inv(S)

        self.x = x_pred + (K @ y).flatten()
        self.P = (np.eye(2) - K @ H) @ P_pred

        return float(self.x[0]), float(self.x[1])


class L2Kalman:
    def __init__(self) -> None:
        q = float(config.get('learning', 'l2_process_noise', default=0.001))
        r = float(config.get('learning', 'l2_measurement_noise', default=0.1))
        self.filters: dict[str, _AssetFilter] = {
            a: _AssetFilter(q, r) for a in ('BTC', 'ETH', 'SOL', 'XRP')
        }

    async def on_tick(self, event: dict) -> None:
        asset = event.get('asset', '')
        filt = self.filters.get(asset)
        if not filt:
            return
        price = float(event.get('price', 0.0))
        ts = float(event.get('timestamp', time.time()))
        if price <= 0:
            return
        kp, kv = filt.update(price, ts)
        state.set_sync(f'learning.l2.kalman.{asset}.x_price', kp)
        state.set_sync(f'learning.l2.kalman.{asset}.x_velocity', kv)
        state.set_sync(f'price.{asset}.kalman_price', kp)
        state.set_sync(f'price.{asset}.kalman_velocity', kv)

    async def run(self) -> None:
        while True:
            await asyncio.sleep(3600)
