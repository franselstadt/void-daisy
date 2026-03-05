"""Cross-asset lag tracker."""

from __future__ import annotations

import asyncio
import json
import time
from collections import defaultdict, deque
from pathlib import Path

from core.event_bus import bus
from core.logger import logger
from core.state import state


class CorrelationTracker:
    def __init__(self, path: str = 'data/correlation_state.json') -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.pending: deque[tuple[float, int]] = deque(maxlen=200)
        self.lags: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=30))

    async def on_major_move(self, event: dict) -> None:
        a = event.get('asset')
        d = 1 if float(event.get('velocity_60s', 0.0)) >= 0 else -1
        ts = float(event.get('timestamp', time.time()))
        if a == 'BTC':
            self.pending.append((ts, d))
            return
        if a not in {'ETH', 'SOL', 'XRP'}:
            return
        for bts, bd in reversed(self.pending):
            if bd != d:
                continue
            lag = ts - bts
            if 0 < lag < 60:
                self.lags[a].append(lag)
                break

    async def run(self) -> None:
        bus.subscribe('MAJOR_MOVE', self.on_major_move)
        while True:
            try:
                out = {a: sum(v) / len(v) for a, v in self.lags.items() if v}
                if out:
                    self.path.write_text(json.dumps(out, indent=2, sort_keys=True))
                    for a, lag in out.items():
                        state.set_sync(f'correlation.lag.{a}', lag)
            except Exception as exc:  # noqa: BLE001
                logger.warning('correlation_tracker_error', error=str(exc))
            await asyncio.sleep(600)
