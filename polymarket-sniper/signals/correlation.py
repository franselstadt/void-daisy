"""Cross-asset correlation lag tracker."""

from __future__ import annotations

import asyncio
import json
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from core.event_bus import bus
from core.logger import logger
from core.state import AppState


class CorrelationEngine:
    """Tracks how ETH/SOL/XRP lag BTC major moves."""

    def __init__(self, state: AppState, path: str | Path = "data/correlation_state.json") -> None:
        self.state = state
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.pending_btc_moves: deque[tuple[float, int]] = deque(maxlen=200)
        self.rolling_lags: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=20))

    async def on_major_move(self, event: dict[str, Any]) -> None:
        """Store BTC move timestamps and align follower response timestamps."""
        asset = event.get("asset")
        velocity = float(event.get("velocity_60s", 0.0))
        direction = 1 if velocity >= 0 else -1
        now = float(event.get("timestamp", time.time()))
        if asset == "BTC":
            self.pending_btc_moves.append((now, direction))
            return

        if asset not in {"ETH", "SOL", "XRP"}:
            return

        for btc_ts, btc_dir in reversed(self.pending_btc_moves):
            if btc_dir != direction:
                continue
            lag = now - btc_ts
            if 0 < lag < 60:
                self.rolling_lags[asset].append(lag)
                break

    async def _persist_loop(self) -> None:
        while True:
            try:
                payload = {asset: sum(vals) / len(vals) for asset, vals in self.rolling_lags.items() if vals}
                self.path.write_text(json.dumps(payload, indent=2, sort_keys=True))
                snap = await self.state.get("correlation_lag", default={})
                snap.update(payload)
                await self.state.set("correlation_lag", value=snap)
            except Exception as exc:  # noqa: BLE001
                logger.warning("correlation_persist_error", error=str(exc))
            await asyncio.sleep(600)

    async def run(self) -> None:
        """Subscribe and persist lag state continuously."""
        bus.subscribe("MAJOR_MOVE", self.on_major_move)
        await self._persist_loop()
