"""Feed supervisor and health checks."""

from __future__ import annotations

import asyncio
import time

from core.logger import logger
from core.state import AppState


class FeedManager:
    """Monitors feed heartbeat timestamps and status."""

    def __init__(self, state: AppState) -> None:
        self.state = state

    async def run(self) -> None:
        """Health loop; warnings only, reconnects handled by feeds."""
        while True:
            snapshot = await self.state.snapshot()
            feed = snapshot.get("feed", {})
            now = time.time()
            for name, data in feed.items():
                if isinstance(data, dict) and "connected" in data:
                    last_seen = float(data.get("last_seen", now))
                    if not data.get("connected", False) or now - last_seen > 60:
                        logger.warning("feed_unhealthy", feed=name, stale_seconds=round(now - last_seen, 3))
            await asyncio.sleep(10)
