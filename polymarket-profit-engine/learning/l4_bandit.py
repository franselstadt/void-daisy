"""L4 Multi-armed bandit plan weighting using UCB1."""

from __future__ import annotations

import asyncio
import json
import math
from pathlib import Path

from core.config import config
from core.state import state


class L4Bandit:
    def __init__(self, path: str = 'data/bandit_state.json') -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.data = self._load()
        self.ucb_c = float(config.get('learning', 'l4_ucb_c', default=1.41))

    def _load(self) -> dict:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text())
            except Exception:
                pass
        return {}

    def _save(self) -> None:
        self.path.write_text(json.dumps(self.data, indent=2, sort_keys=True))

    async def on_trade_exit(self, event: dict) -> None:
        plan = str(event.get('plan', ''))
        if not plan:
            return
        won = int(event.get('won', 0)) == 1
        entry_price = float(event.get('entry_price', 0.5))
        pnl_pct = float(event.get('pnl_pct', 0.0))
        reward = pnl_pct if won else -entry_price

        arm = self.data.setdefault(plan, {'pulls': 0, 'total_reward': 0.0})
        arm['pulls'] += 1
        arm['total_reward'] += reward

    async def run(self) -> None:
        while True:
            total_pulls = sum(a.get('pulls', 0) for a in self.data.values())
            if total_pulls == 0:
                total_pulls = 1

            for i in range(1, 13):
                plan = f'PLAN_{i:02d}'
                arm = self.data.setdefault(plan, {'pulls': 0, 'total_reward': 0.0})
                pulls = max(1, arm['pulls'])
                avg_reward = arm['total_reward'] / pulls
                exploration = self.ucb_c * math.sqrt(math.log(total_pulls) / pulls)
                ucb = avg_reward + exploration
                arm['ucb_score'] = round(ucb, 4)
                state.set_sync(f'learning.l4.bandit.{plan}.pulls', arm['pulls'])
                state.set_sync(f'learning.l4.bandit.{plan}.total_reward', arm['total_reward'])
                state.set_sync(f'learning.l4.bandit.{plan}.ucb_score', ucb)
                state.set_sync(f'plan.{plan}.ucb_score', ucb)

            self._save()
            await asyncio.sleep(120)
