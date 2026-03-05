"""Coordinator for all 8 learning systems.

Event wiring:
  TRADE_EXITED → L1 (Bayesian), L4 (bandit), L5 (gradient), L7 (RL)
  PRICE_TICK   → L2 (Kalman, every tick)
  TRADE_EXITED → L6 (correlation, PLAN_03 trades only)
  Every 60s    → L3 (HMM regime update)
  Every 300s   → L5 gradient batch update
  Every 3600s  → L8 (threshold calibration)
  THOUGHT_TRAIN_COMPLETED → L8
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
        await asyncio.gather(
            self.l1.run(),
            self.l2.run(),
            self.l3.run(),
            self.l4.run(),
            self.l5.run(),
            self.l6.run(),
            self.l7.run(),
            self.l8.run(),
        )
