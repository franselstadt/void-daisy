"""Coordinator for all 8 learning systems."""

from __future__ import annotations

import asyncio

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
        self.systems = [L1Bayesian(), L2Kalman(), L3HMM(), L4Bandit(), L5Gradient(), L6Correlation(), L7RLSizer(), L8Calibrator()]

    async def run(self) -> None:
        await asyncio.gather(*[s.run() for s in self.systems])
