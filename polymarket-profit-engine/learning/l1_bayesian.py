"""L1 Bayesian signal updater."""

from __future__ import annotations

import asyncio
import json
from math import sqrt
from pathlib import Path

from core.event_bus import bus
from core.state import state


class L1Bayesian:
    def __init__(self, path: str = 'data/bayesian_beliefs.json') -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.beliefs = self._load()

    def _load(self) -> dict:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text())
            except Exception:
                return {}
        return {}

    def _save(self) -> None:
        self.path.write_text(json.dumps(self.beliefs, indent=2, sort_keys=True))

    def _w(self, age: float) -> float:
        if age < 600: return 4.0
        if age < 1800: return 2.5
        if age < 3600: return 1.5
        if age < 10800: return 1.0
        return 0.5

    async def on_exit(self, event: dict) -> None:
        import time
        age = time.time() - float(event.get('timestamp', time.time()))
        w = self._w(age)
        won = int(event.get('won', 0)) == 1
        signals = event.get('signals_fired', [])
        for s in signals:
            b = self.beliefs.setdefault(s, {'alpha': 1.0, 'beta': 1.0})
            if won:
                b['alpha'] += w
            else:
                b['beta'] += w
            a, bt = b['alpha'], b['beta']
            exp = a / (a + bt)
            unc = sqrt(a * bt / (((a + bt) ** 2) * (a + bt + 1)))
            b['expected_win_rate'] = exp
            b['conservative_estimate'] = exp - 0.5 * unc
            state.set_sync(f'learning.l1.win_rate.{s}', b['conservative_estimate'])
        state.set_sync('learning.l1.beliefs', self.beliefs)

    async def run(self) -> None:
        bus.subscribe('TRADE_EXITED', self.on_exit)
        while True:
            self._save()
            await asyncio.sleep(600)
