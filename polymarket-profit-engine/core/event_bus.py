"""Async event bus using asyncio.Queue.

Events:
    PRICE_TICK            – Binance price update
    MAJOR_MOVE            – Large single-tick move detected
    VOLUME_SPIKE          – Unusual volume burst on Binance
    VELOCITY_REVERSAL     – Price velocity direction flip
    POLYMARKET_TICK       – Polymarket orderbook update
    PRICE_CRASH           – Polymarket crash detected
    CHAINLINK_UPDATE      – Chainlink oracle price update
    ORACLE_UPDATED        – Oracle price refreshed
    ORACLE_LAG_DETECTED   – Oracle lagging behind market
    FEED_DISCONNECTED     – WebSocket feed lost
    FEED_RECONNECTED      – WebSocket feed restored
    OPPORTUNITY_DETECTED  – Plan engine found a trade opportunity
    SCHEDULED_OPPORTUNITY – Window scheduler emitted opportunity
    TRADE_BLOCKED         – Guardian / risk blocked a trade
    TRADE_ENTERED         – Order filled (entry)
    TRADE_EXITED          – Position closed (exit)
    TRADE_EXIT_REQUEST    – Profit-taker requests exit
    ORDER_FAILED          – Order placement failed
    STOP_LOSS_HIT         – Stop-loss triggered
    DRAWDOWN_WARNING      – Drawdown threshold warning
    DRAWDOWN_CRITICAL     – Drawdown critical level
    DEGRADATION_LEVEL_CHANGED – Risk degradation level changed
    REGIME_CHANGED        – Market regime shift detected
    COVERAGE_ALERT        – Feed coverage gap alert
    COVERAGE_FAILURE      – Feed coverage failure
    WEIGHTS_UPDATED       – L5 gradient updated plan weights
    THOUGHT_TRAIN_TRIGGERED – Thought-train analysis started
    THOUGHT_TRAIN_COMPLETED – Thought-train analysis finished
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from loguru import logger

Handler = Callable[..., Any]


class EventBus:
    def __init__(self) -> None:
        self._q: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue(maxsize=100_000)
        self._handlers: dict[str, list[Handler]] = defaultdict(list)

    def subscribe(self, event_type: str, handler: Handler) -> None:
        self._handlers[event_type].append(handler)

    async def publish(self, event_type: str, data: dict[str, Any]) -> None:
        try:
            self._q.put_nowait((event_type, data))
        except asyncio.QueueFull:
            logger.error('event_queue_full event={}', event_type)

    async def run(self) -> None:
        while True:
            event, payload = await self._q.get()
            for handler in self._handlers.get(event, []):
                if asyncio.iscoroutinefunction(handler):
                    asyncio.create_task(handler(payload))
                else:
                    handler(payload)


bus = EventBus()
