"""Lightweight HMM-like regime confidence using Gaussian mixture."""

from __future__ import annotations

import asyncio
import pickle
from pathlib import Path

import numpy as np
from sklearn.mixture import GaussianMixture

from core.logger import logger
from core.state import state


class HMMDetector:
    def __init__(self, path: str = 'data/hmm_model.pkl') -> None:
        self.path = Path(path)
        self.model: GaussianMixture | None = None
        if self.path.exists():
            try:
                self.model = pickle.loads(self.path.read_bytes())
            except Exception:
                self.model = None

    def _save(self) -> None:
        if self.model is not None:
            self.path.write_bytes(pickle.dumps(self.model))

    async def run(self) -> None:
        while True:
            try:
                data = np.array(list(state.get('history.BTC.velocity_60s', []))[-180:]).reshape(-1, 1)
                if len(data) >= 60:
                    self.model = GaussianMixture(n_components=3, random_state=42)
                    self.model.fit(data)
                    probs = self.model.predict_proba(data[-1:])[0]
                    conf = float(np.max(probs))
                    state.set_sync('bot.regime_confidence', conf)
                    self._save()
            except Exception as exc:  # noqa: BLE001
                logger.warning('hmm_detector_error', error=str(exc))
            await asyncio.sleep(300)
