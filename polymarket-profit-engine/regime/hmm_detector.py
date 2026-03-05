"""Lightweight HMM-like regime confidence using Gaussian mixture."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import numpy as np
from sklearn.mixture import GaussianMixture

from core.logger import logger
from core.state import state


class HMMDetector:
    def __init__(self, model_dir: str = 'data') -> None:
        self.params_path = Path(model_dir) / 'hmm_params.json'
        self.model: GaussianMixture | None = None
        self._load()

    def _load(self) -> None:
        if not self.params_path.exists():
            return
        try:
            params = json.loads(self.params_path.read_text())
            self.model = GaussianMixture(n_components=params['n_components'], random_state=42)
            self.model.means_ = np.array(params['means'])
            self.model.covariances_ = np.array(params['covariances'])
            self.model.weights_ = np.array(params['weights'])
            self.model.precisions_cholesky_ = np.array(params['precisions_cholesky'])
            self.model.converged_ = True
        except Exception:
            self.model = None

    def _save(self) -> None:
        if self.model is None:
            return
        try:
            params = {
                'n_components': self.model.n_components,
                'means': self.model.means_.tolist(),
                'covariances': self.model.covariances_.tolist(),
                'weights': self.model.weights_.tolist(),
                'precisions_cholesky': self.model.precisions_cholesky_.tolist(),
            }
            self.params_path.write_text(json.dumps(params, indent=2))
        except Exception as exc:
            logger.warning('hmm_save_error', error=str(exc))

    async def run(self) -> None:
        while True:
            try:
                raw = list(state.get('history.BTC.velocity_60s', []))[-180:]
                data = np.array(raw).reshape(-1, 1)
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
