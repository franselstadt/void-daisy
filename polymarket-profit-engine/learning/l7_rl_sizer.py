"""L7 RL-style position sizing adapter."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from core.state import state


class L7RLSizer:
    def __init__(self, path: str = 'data/rl_sizer_state.json') -> None:
        self.path = Path(path)
        self.state = {'multiplier': 1.0}
        if self.path.exists():
            try:
                self.state = json.loads(self.path.read_text())
            except Exception:
                self.state = {'multiplier': 1.0}

    async def run(self) -> None:
        while True:
            wr10 = float(state.get('stats.win_rate_10', 0.5))
            if wr10 > 0.65:
                self.state['multiplier'] = min(1.2, self.state['multiplier'] + 0.01)
            elif wr10 < 0.45:
                self.state['multiplier'] = max(0.7, self.state['multiplier'] - 0.02)
            state.set_sync('learning.l7.rl_sizer.multiplier', self.state['multiplier'])
            self.path.write_text(json.dumps(self.state, indent=2))
            await asyncio.sleep(120)
