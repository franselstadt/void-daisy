"""L4 Multi-armed bandit plan weighting."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from core.state import state


class L4Bandit:
    def __init__(self, path: str = 'data/bandit_state.json') -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            try:
                self.data = json.loads(self.path.read_text())
            except Exception:
                self.data = {}
        else:
            self.data = {}

    def _save(self) -> None:
        self.path.write_text(json.dumps(self.data, indent=2, sort_keys=True))

    async def run(self) -> None:
        while True:
            # simple epsilon-greedy values persisted in state
            for i in range(1, 13):
                plan = f'PLAN_{i:02d}'
                wr = float(state.get(f'stats.win_rate_20.{plan}', 0.5))
                self.data.setdefault(plan, {'value': 0.5, 'count': 1})
                self.data[plan]['value'] = self.data[plan]['value'] * 0.9 + wr * 0.1
                self.data[plan]['count'] += 1
                state.set_sync(f'learning.l4.bandit.{plan}.value', self.data[plan]['value'])
            self._save()
            await asyncio.sleep(120)
