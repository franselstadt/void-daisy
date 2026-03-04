"""Thread-safe/async-safe mutable bot state."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from typing import Any


class AppState:
    """Single mutable state container protected by asyncio.Lock."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._state: dict[str, Any] = {
            "bankroll": 200.0,
            "starting_bankroll": 200.0,
            "consecutive_losses": 0,
            "win_rate_10": 0.5,
            "degradation_level": 0,
            "open_positions": {},
            "feed": {"binance": {}, "polymarket": {"connected": False}, "chainlink": {"connected": False}},
            "oracle": {},
            "latest_spot": {},
            "latest_ticks": {},
            "latest_polymarket": {},
            "bot": {"paused": False, "emergency_stopped": False, "hard_stopped": False},
            "metrics": {"last_10": [], "total_trades": 0},
            "xrp": {"news_blackout_active": False, "blackout_until": 0.0},
            "version": {"config": 1, "weights": 1},
        }

    async def get(self, *keys: str, default: Any = None) -> Any:
        """Read nested key path from state."""
        async with self._lock:
            current: Any = self._state
            for key in keys:
                if not isinstance(current, dict) or key not in current:
                    return default
                current = current[key]
            return deepcopy(current)

    async def set(self, *keys: str, value: Any) -> None:
        """Set nested key path in state."""
        if not keys:
            return
        async with self._lock:
            current = self._state
            for key in keys[:-1]:
                current = current.setdefault(key, {})
            current[keys[-1]] = value

    async def update(self, patch: dict[str, Any]) -> None:
        """Shallow-merge top-level state entries."""
        async with self._lock:
            for key, value in patch.items():
                if isinstance(value, dict) and isinstance(self._state.get(key), dict):
                    self._state[key].update(value)
                else:
                    self._state[key] = value

    async def snapshot(self) -> dict[str, Any]:
        """Get deep-copied state snapshot."""
        async with self._lock:
            return deepcopy(self._state)


state = AppState()
