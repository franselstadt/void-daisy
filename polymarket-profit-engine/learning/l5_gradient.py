"""L5 online gradient-style weight optimizer."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from core.event_bus import bus


class L5Gradient:
    def __init__(self, path: str = 'data/signal_weights.json') -> None:
        self.path = Path(path)

    async def run(self) -> None:
        while True:
            try:
                weights = json.loads(self.path.read_text()) if self.path.exists() else {}
                # conservative decay toward stability, no large swings
                for k, v in list(weights.items()):
                    weights[k] = max(0.1, min(3.0, v * 0.999))
                self.path.write_text(json.dumps(weights, indent=2, sort_keys=True))
                await bus.publish('WEIGHTS_UPDATED', {'trigger': 'L5_GRADIENT'})
            except Exception:
                pass
            await asyncio.sleep(900)
