"""Asynchronous event bus for decoupled system communication."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

from core.logger import logger

EventHandler = Callable[[dict[str, Any]], Awaitable[None]]


class EventBus:
    """Queue-backed async event bus with fire-and-forget handlers."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue(maxsize=10_000)
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        """Register an async handler for an event type."""
        self._handlers[event_type].append(handler)

    async def publish(self, event_type: str, data: dict[str, Any]) -> None:
        """Publish an event; drop only when queue is full."""
        try:
            self._queue.put_nowait((event_type, data))
        except asyncio.QueueFull:
            logger.error("event_bus_queue_full", event_type=event_type)

    async def _run_handler(self, handler: EventHandler, event_type: str, data: dict[str, Any]) -> None:
        """Run handler safely without crashing the bus."""
        try:
            await handler(data)
        except Exception as exc:  # noqa: BLE001
            logger.exception("event_handler_error", event_type=event_type, error=str(exc))

    async def run(self) -> None:
        """Drain queue forever and dispatch handler tasks."""
        logger.info("event_bus_started")
        while True:
            event_type, data = await self._queue.get()
            handlers = self._handlers.get(event_type, [])
            for handler in handlers:
                asyncio.create_task(self._run_handler(handler, event_type, data))


bus = EventBus()

EVENT_TYPES = {
    "PRICE_TICK",
    "POLYMARKET_TICK",
    "CHAINLINK_UPDATE",
    "ORACLE_LAG_DETECTED",
    "ORACLE_UPDATED",
    "FEED_DISCONNECTED",
    "FEED_RECONNECTED",
    "SNIPE_OPPORTUNITY",
    "MAJOR_MOVE",
    "CROSS_ASSET_LAG",
    "VOLUME_SPIKE",
    "VELOCITY_REVERSAL",
    "PRICE_CRASH",
    "MOMENTUM_REVERSAL",
    "TRADE_ENTERED",
    "TRADE_EXITED",
    "TRADE_BLOCKED",
    "STOP_LOSS_HIT",
    "PROFIT_TARGET_HIT",
    "ORDER_FAILED",
    "DRAWDOWN_WARNING",
    "DRAWDOWN_CRITICAL",
    "SIZE_REDUCED",
    "SIZE_RESTORED",
    "WEIGHTS_UPDATED",
    "BELIEFS_UPDATED",
    "THOUGHT_TRAIN_TRIGGERED",
    "THOUGHT_TRAIN_COMPLETED",
    "CONFIG_UPDATED",
    "BACKTEST_COMPLETE",
    "TRADE_EXIT_REQUEST",
    "DEGRADATION_LEVEL_CHANGED",
    "REGIME_CHANGED",
    "OPPORTUNITY_DETECTED",
    "SCHEDULED_OPPORTUNITY",
    "COVERAGE_ALERT",
    "COVERAGE_FAILURE",
}
