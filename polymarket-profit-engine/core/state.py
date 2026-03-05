"""Thread-safe global state with dot-notation keys."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from typing import Any


class State:
    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._lock = asyncio.Lock()

    async def set(self, key: str, value: Any) -> None:
        async with self._lock:
            self._nest(key, value)

    def set_sync(self, key: str, value: Any) -> None:
        self._nest(key, value)

    def get(self, key: str, default: Any = None) -> Any:
        parts = key.split('.')
        data: Any = self._data
        for p in parts:
            if not isinstance(data, dict) or p not in data:
                return default
            data = data[p]
        return deepcopy(data)

    async def delete(self, key: str) -> None:
        async with self._lock:
            parts = key.split('.')
            data: Any = self._data
            for p in parts[:-1]:
                if not isinstance(data, dict) or p not in data:
                    return
                data = data[p]
            if isinstance(data, dict):
                data.pop(parts[-1], None)

    def append_list(self, key: str, value: Any, maxlen: int = 200) -> None:
        lst = list(self.get(key, []))
        lst.append(value)
        if len(lst) > maxlen:
            lst = lst[-maxlen:]
        self.set_sync(key, lst)

    def snapshot(self) -> dict[str, Any]:
        return deepcopy(self._data)

    def _nest(self, key: str, value: Any) -> None:
        parts = key.split('.')
        data: dict[str, Any] = self._data
        for p in parts[:-1]:
            item = data.get(p)
            if not isinstance(item, dict):
                data[p] = {}
            data = data[p]
        data[parts[-1]] = value


state = State()
