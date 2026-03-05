"""Coordinator for all 8 learning systems.

Wiring:
  TRADE_EXITED  → L1 (Bayesian), L4 (Bandit), L5 (Gradient), L7 (RL Sizer)
  PRICE_TICK    → L2 (Kalman)
  every ~60s    → L3 (HMM) via its own run loop
  every ~3600s  → L8 (Calibrator) via its own run loop
  every ~300s   → L5 batch gradient update via its own run loop
"""

from __future__ import annotations

import asyncio

from core.event_bus import bus
from learning.l1_bayesian import L1Bayesian
from learning.l2_kalman import L2Kalman
from learning.l3_hmm import L3HMM
from learning.l4_bandit import L4Bandit
from learning.l5_gradient import L5Gradient
from learning.l6_correlation import L6Correlation
from learning.l7_rl_sizer import L7RLSizer
from learning.l8_calibrator import L8Calibrator


class LearningCoordinator:
    def __init__(self) -> None:
        self.l1 = L1Bayesian()
        self.l2 = L2Kalman()
        self.l3 = L3HMM()
        self.l4 = L4Bandit()
        self.l5 = L5Gradient()
        self.l6 = L6Correlation()
        self.l7 = L7RLSizer()
        self.l8 = L8Calibrator()
        self.systems = [self.l1, self.l2, self.l3, self.l4, self.l5, self.l6, self.l7, self.l8]

    def _wire_events(self) -> None:
        bus.subscribe('TRADE_EXITED', self.l1.on_exit)
        bus.subscribe('PRICE_TICK', self.l2.on_tick)
        bus.subscribe('TRADE_EXITED', self.l4.on_trade_exit)
        bus.subscribe('TRADE_EXITED', self.l5.on_exit)
        bus.subscribe('TRADE_EXITED', self.l6.on_trade_exit)
        bus.subscribe('TRADE_EXITED', self.l7.on_trade_exit)
        bus.subscribe('THOUGHT_TRAIN_COMPLETED', self.l8.on_thought_train)

    async def run(self) -> None:
        self._wire_events()
        await asyncio.gather(*[s.run() for s in self.systems])
