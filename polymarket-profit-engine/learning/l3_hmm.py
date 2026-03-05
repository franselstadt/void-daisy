"""L3 wrapper around HMM detector outputs."""

from __future__ import annotations

import asyncio

from regime.hmm_detector import HMMDetector


class L3HMM:
    def __init__(self) -> None:
        self.detector = HMMDetector()

    async def run(self) -> None:
        await self.detector.run()
