"""L5 online gradient descent weight optimizer."""

from __future__ import annotations

import asyncio
import json
from collections import deque
from pathlib import Path

from core.config import config
from core.event_bus import bus
from core.state import state


class L5Gradient:
    def __init__(self, path: str = 'data/signal_weights.json') -> None:
        self.path = Path(path)
        self.trades: deque[dict] = deque(maxlen=100)
        self.lr = float(config.get('learning', 'l5_learning_rate', default=0.01))
        self.max_change = float(config.get('learning', 'l5_max_weight_change', default=0.20))
        self.last_loss = float('inf')

    async def on_exit(self, event: dict) -> None:
        self.trades.append(event)

    async def run(self) -> None:
        bus.subscribe('TRADE_EXITED', self.on_exit)
        while True:
            await asyncio.sleep(900)
            if len(self.trades) < 10:
                continue
            try:
                weights = json.loads(self.path.read_text()) if self.path.exists() else {}
                if not weights:
                    continue

                loss = 0.0
                gradients: dict[str, float] = {k: 0.0 for k in weights}
                count = 0

                for trade in self.trades:
                    conf = float(trade.get('confidence', 0.5))
                    outcome = 1.0 if int(trade.get('won', 0)) == 1 else 0.0
                    error = conf - outcome
                    loss += error ** 2
                    signals = trade.get('signals_fired', [])
                    for s in signals:
                        if s in gradients:
                            gradients[s] += 2 * error
                    count += 1

                if count == 0:
                    continue
                loss /= count
                for s in gradients:
                    gradients[s] /= count

                if loss < self.last_loss:
                    self.lr = min(0.05, self.lr * 1.1)
                else:
                    self.lr = max(0.001, self.lr * 0.8)
                self.last_loss = loss

                changed = False
                for s, grad in gradients.items():
                    if abs(grad) < 1e-6:
                        continue
                    old_w = weights[s]
                    delta = -self.lr * grad
                    delta = max(-old_w * self.max_change, min(old_w * self.max_change, delta))
                    new_w = max(0.1, min(3.0, old_w + delta))
                    if abs(new_w - old_w) > 1e-6:
                        weights[s] = round(new_w, 4)
                        changed = True

                if changed:
                    self.path.write_text(json.dumps(weights, indent=2, sort_keys=True))
                    await bus.publish('WEIGHTS_UPDATED', {'trigger': 'L5_GRADIENT', 'loss': loss})

                state.set_sync('learning.l5.last_loss', loss)
                state.set_sync('learning.l5.learning_rate', self.lr)

            except Exception:
                pass
