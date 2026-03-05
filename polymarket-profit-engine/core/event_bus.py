"""Async event bus using asyncio.Queue."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

from core.logger import logger

Handler = Callable[[dict[str, Any]], Awaitable[None]]


class EventBus:
    def __init__(self) -> None:
        self._q: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue(maxsize=10000)
        self._handlers: dict[str, list[Handler]] = defaultdict(list)

    def subscribe(self, event_type: str, handler: Handler) -> None:
        self._handlers[event_type].append(handler)

    async def publish(self, event_type: str, data: dict[str, Any]) -> None:
        try:
            self._q.put_nowait((event_type, data))
        except asyncio.QueueFull:
            logger.error('event_queue_full', event=event_type)

    async def _safe_call(self, fn: Handler, event_type: str, payload: dict[str, Any]) -> None:
        try:
            await fn(payload)
        except Exception as exc:  # noqa: BLE001
            logger.exception('event_handler_error', event=event_type, error=str(exc))

    async def run(self) -> None:
        while True:
            event, payload = await self._q.get()
            for fn in self._handlers.get(event, []):
                asyncio.create_task(self._safe_call(fn, event, payload))


bus = EventBus()
