"""L7 RL-style position sizing adapter with Q-table.

State space (10 bins each):
  - win_rate_10: [0.0 .. 1.0]
  - drawdown_pct: [0.0 .. 0.20]

Action space (5 bins):
  - size multiplier: [0.5, 0.7, 0.85, 1.0, 1.2]

Epsilon-greedy policy with decaying epsilon.
"""

from __future__ import annotations

import asyncio
import json
import random
from pathlib import Path

from core.config import config
from core.event_bus import bus
from core.state import state

STATE_BINS = 10
ACTION_BINS = 5
ACTIONS = [0.5, 0.7, 0.85, 1.0, 1.2]


class L7RLSizer:
    def __init__(self, path: str = 'data/rl_sizer_state.json') -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.discount = float(config.get('learning', 'l7_discount', default=0.95))
        self.lr = 0.1
        self.epsilon = 0.15
        self.q_table: dict[str, list[float]] = {}
        self.multiplier = 1.0
        self._last_state_key: str | None = None
        self._last_action_idx: int | None = None
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text())
                self.q_table = data.get('q_table', {})
                self.epsilon = data.get('epsilon', 0.15)
                self.multiplier = data.get('multiplier', 1.0)
                return
            except Exception:
                pass
        self.q_table = {}
        self.epsilon = 0.15
        self.multiplier = 1.0

    def _save(self) -> None:
        self.path.write_text(json.dumps({
            'q_table': self.q_table,
            'epsilon': round(self.epsilon, 6),
            'multiplier': round(self.multiplier, 4),
        }, indent=2, sort_keys=True))

    @staticmethod
    def _discretize(win_rate_10: float, drawdown_pct: float) -> str:
        wr_bin = min(STATE_BINS - 1, max(0, int(win_rate_10 * STATE_BINS)))
        dd_bin = min(STATE_BINS - 1, max(0, int(drawdown_pct / 0.20 * STATE_BINS)))
        return f'{wr_bin}_{dd_bin}'

    def _get_q(self, key: str) -> list[float]:
        if key not in self.q_table:
            self.q_table[key] = [0.0] * ACTION_BINS
        return self.q_table[key]

    def _choose_action(self, key: str) -> int:
        q = self._get_q(key)
        if random.random() < self.epsilon:
            return random.randint(0, ACTION_BINS - 1)
        return int(max(range(ACTION_BINS), key=lambda i: q[i]))

    async def on_trade_exit(self, event: dict) -> None:
        reward = float(event.get('pnl_pct', 0.0))
        won = int(event.get('won', 0)) == 1
        if not won:
            reward = min(reward, -float(event.get('entry_price', 0.5)))

        wr10 = float(state.get('stats.win_rate_10', 0.5))
        dd = float(state.get('stats.drawdown_pct', 0.0))
        new_key = self._discretize(wr10, dd)

        if self._last_state_key is not None and self._last_action_idx is not None:
            old_q = self._get_q(self._last_state_key)
            new_q = self._get_q(new_key)
            best_next = max(new_q)
            old_val = old_q[self._last_action_idx]
            old_q[self._last_action_idx] = old_val + self.lr * (
                reward + self.discount * best_next - old_val
            )

        action_idx = self._choose_action(new_key)
        self._last_state_key = new_key
        self._last_action_idx = action_idx
        self.multiplier = ACTIONS[action_idx]

        self.epsilon = max(0.02, self.epsilon * 0.999)

        state.set_sync('learning.l7.rl_sizer.multiplier', self.multiplier)
        state.set_sync('learning.l7.rl_sizer.epsilon', self.epsilon)

    async def run(self) -> None:
        bus.subscribe('TRADE_EXITED', self.on_trade_exit)
        while True:
            state.set_sync('learning.l7.rl_sizer.multiplier', self.multiplier)
            self._save()
            await asyncio.sleep(120)
