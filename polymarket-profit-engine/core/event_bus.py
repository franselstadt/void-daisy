"""Async event bus using asyncio.Queue.

ALL EVENTS IN THE SYSTEM:
  PRICE_TICK            — every Binance trade tick
  MAJOR_MOVE            — >0.3% move in 60s on any asset
  VOLUME_SPIKE          — volume 3x+ average
  POLYMARKET_TICK       — every CLOB price update
  PRICE_CRASH           — >0.15 crash in one tick on Polymarket
  ORACLE_LAG_DETECTED   — Chainlink lagging Binance >2.5s
  ORACLE_UPDATED        — Chainlink price changed
  CHAINLINK_UPDATE      — every Chainlink poll
  REGIME_CHANGED        — market regime changed
  SNIPE_OPPORTUNITY     — any plan found a trade
  SCHEDULED_OPPORTUNITY — window scheduler found a trade
  OPPORTUNITY_DETECTED  — engine manager detected opportunity
  TRADE_ENTERED         — position opened
  TRADE_EXITED          — position closed (any reason)
  TRADE_EXIT_REQUEST    — profit taker requests exit
  TRADE_BLOCKED         — guardian blocked a trade
  ORDER_FAILED          — order placement failed
  AUTO_PROFIT_TAKEN     — profit taker auto-exited
  STOP_LOSS_HIT         — stop loss triggered
  BACKUP_EXIT_TRIGGERED — backup exit plan executed
  WINDOW_EXPIRED        — trade blocked: window expired
  STALE_DATA_BLOCKED    — trade blocked: data too old
  COVERAGE_ALERT        — asset not traded in 6 minutes
  COVERAGE_FAILURE      — extended coverage gap with diagnostics
  WEIGHTS_UPDATED       — learning system updated weights
  REGIME_FITNESS_UPDATED — plan fitness scores updated
  DEGRADATION_LEVEL_CHANGED — degradation level changed
  THOUGHT_TRAIN_TRIGGERED — thought train started
  THOUGHT_TRAIN_COMPLETED — diagnosis completed
  DRAWDOWN_WARNING      — drawdown threshold exceeded
  DRAWDOWN_CRITICAL     — bankroll critically low
  FEED_RECONNECTED      — data feed reconnected
  FEED_DISCONNECTED     — data feed lost
  VELOCITY_REVERSAL     — velocity direction reversed
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

from loguru import logger


class EventBus:
    def __init__(self) -> None:
        self._subs: dict[str, list] = defaultdict(list)
        self._queue: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue(maxsize=100_000)

    def subscribe(self, event: str, handler) -> None:  # noqa: ANN001
        self._subs[event].append(handler)

    async def publish(self, event: str, data: dict[str, Any]) -> None:
        try:
            self._queue.put_nowait((event, data))
        except asyncio.QueueFull:
            logger.warning(f"Event queue full, dropping: {event}")

    async def run(self) -> None:
        while True:
            event, data = await self._queue.get()
            for handler in self._subs.get(event, []):
                try:
                    if asyncio.iscoroutinefunction(handler):
                        asyncio.create_task(handler(data))
                    else:
                        handler(data)
                except Exception as e:
                    logger.error(f"Bus handler error [{event}]: {e}")


bus = EventBus()
