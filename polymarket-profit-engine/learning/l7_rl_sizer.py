"""L7 RL position sizer with Q-table and epsilon-greedy policy.

State: (win_rate_10 bin, drawdown_pct bin) — 10x10 grid
Actions: [0.5, 0.7, 0.85, 1.0, 1.2] size multipliers
"""

from __future__ import annotations

import asyncio
import json
import random
from collections import defaultdict
from pathlib import Path

from core.config import config
from core.state import state

ACTIONS = [0.5, 0.7, 0.85, 1.0, 1.2]
N_BINS = 10


def _bin(value: float, lo: float = 0.0, hi: float = 1.0) -> int:
    return max(0, min(N_BINS - 1, int((value - lo) / max(hi - lo, 1e-9) * N_BINS)))


def _state_key() -> str:
    wr = _bin(float(state.get('stats.win_rate_10', 0.5)))
    dd = _bin(float(state.get('stats.drawdown_pct', 0.0)), 0.0, 0.3)
    return f'{wr}_{dd}'


class L7RLSizer:
    def __init__(self, path: str = 'data/rl_sizer_state.json') -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.discount = float(config.get('learning', 'l7_discount', default=0.95))
        self.lr = 0.05
        self.epsilon = 0.15
        self.q_table: dict[str, list[float]] = defaultdict(lambda: [0.0] * len(ACTIONS))
        self.last_state: str = ''
        self.last_action_idx: int = 3
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text())
                if isinstance(data.get('q_table'), dict):
                    for k, v in data['q_table'].items():
                        self.q_table[k] = v
                self.epsilon = float(data.get('epsilon', 0.15))
            except Exception:
                pass

    def _save(self) -> None:
        data = {
            'q_table': dict(self.q_table),
            'epsilon': self.epsilon,
            'multiplier': ACTIONS[self.last_action_idx],
        }
        self.path.write_text(json.dumps(data, indent=2))

    def _select_action(self, sk: str) -> int:
        if random.random() < self.epsilon:
            return random.randrange(len(ACTIONS))
        q = self.q_table[sk]
        return int(max(range(len(q)), key=lambda i: q[i]))

    async def on_trade_exit(self, event: dict) -> None:
        won = int(event.get('won', 0)) == 1
        entry_price = float(event.get('entry_price', 0.5))
        pnl_pct = float(event.get('pnl_pct', 0.0))
        dd = float(state.get('stats.drawdown_pct', 0.0))

        reward = pnl_pct / max(abs(dd) + 0.01, 0.01) if won else -entry_price * 3

        sk = _state_key()
        old_q = self.q_table[self.last_state]
        new_q = self.q_table[sk]
        best_next = max(new_q)
        old_q[self.last_action_idx] += self.lr * (reward + self.discount * best_next - old_q[self.last_action_idx])

        self.last_state = sk
        self.last_action_idx = self._select_action(sk)
        state.set_sync('learning.l7.rl_sizer.multiplier', ACTIONS[self.last_action_idx])

        self.epsilon = max(0.02, self.epsilon * 0.999)
        self._save()

    async def run(self) -> None:
        while True:
            sk = _state_key()
            self.last_state = sk
            self.last_action_idx = self._select_action(sk)
            state.set_sync('learning.l7.rl_sizer.multiplier', ACTIONS[self.last_action_idx])
            self._save()
            await asyncio.sleep(120)
