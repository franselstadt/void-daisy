"""Risk monitor and participation coverage monitors."""

from __future__ import annotations

import asyncio
import time

from core.event_bus import bus
from core.logger import logger
from core.state import AppState
from risk.degrader import Degrader


class RiskMonitor:
    """Continuously evaluates drawdown and streak risk state."""

    def __init__(self, state: AppState, degrader: Degrader) -> None:
        self.state = state
        self.degrader = degrader

    async def run(self) -> None:
        """Compute level every few seconds and emit events on changes."""
        tick = 0
        while True:
            snapshot = await self.state.snapshot()
            bankroll = float(snapshot.get("bankroll", 0.0))
            high_watermark = max(float(snapshot.get("high_watermark_bankroll", bankroll)), bankroll)
            await self.state.set("high_watermark_bankroll", value=high_watermark)
            drawdown = max(0.0, (high_watermark - bankroll) / max(high_watermark, 1e-9))
            losses = int(snapshot.get("consecutive_losses", 0))
            win_rate_10 = float(snapshot.get("win_rate_10", 0.5))
            if drawdown > 0.15:
                await bus.publish("DRAWDOWN_WARNING", {"drawdown_pct": drawdown})

            tick += 1
            if tick % 6 == 0:
                level = self.degrader.evaluate(losses, drawdown, win_rate_10)
                current = int(snapshot.get("degradation_level", 0))
                if level != current:
                    await self.state.set("degradation_level", value=level)
                    await bus.publish("DEGRADATION_LEVEL_CHANGED", {"old": current, "new": level, "profile": self.degrader.profile(level)})

            if bankroll < 10 and not snapshot.get("bot", {}).get("hard_stopped", False):
                bot = snapshot.get("bot", {})
                bot["hard_stopped"] = True
                await self.state.set("bot", value=bot)
                await bus.publish("DRAWDOWN_CRITICAL", {"bankroll": bankroll, "hard_stop": True})

            await asyncio.sleep(10)


class CoverageMonitor:
    """Enforces systematic participation with 6-minute coverage checks."""

    COVERAGE_WINDOW_SECONDS = 360

    def __init__(self, state: AppState) -> None:
        self.state = state

    async def record_attempt(self, asset: str) -> None:
        """Record any trade attempt on asset and clear misses."""
        coverage = await self.state.get("coverage", default={})
        coverage.setdefault("last_attempt", {})[asset] = time.time()
        coverage.setdefault("misses", {})[asset] = 0
        coverage.setdefault("threshold_relax", {}).pop(asset, None)
        await self.state.set("coverage", value=coverage)

    async def run(self) -> None:
        """Check coverage gaps every minute."""
        while True:
            await self._check_coverage()
            await asyncio.sleep(60)

    async def _check_coverage(self) -> None:
        now = time.time()
        snapshot = await self.state.snapshot()
        coverage = snapshot.get("coverage", {})
        last_attempt = coverage.get("last_attempt", {})
        misses = coverage.get("misses", {})
        relax = coverage.get("threshold_relax", {})
        for asset in ["BTC", "ETH", "SOL", "XRP"]:
            gap = now - float(last_attempt.get(asset, 0.0))
            if gap <= self.COVERAGE_WINDOW_SECONDS:
                misses[asset] = 0
                relax.pop(asset, None)
                continue
            misses[asset] = int(misses.get(asset, 0)) + 1
            count = misses[asset]
            logger.warning("coverage_gap", asset=asset, gap_minutes=round(gap / 60, 2), misses=count)
            if count == 1:
                relax[asset] = 0.90
            elif count == 2:
                relax[asset] = 0.80
                await bus.publish("COVERAGE_ALERT", {"asset": asset, "gap_minutes": round(gap / 60, 2), "misses": count})
            else:
                reasons: list[str] = []
                if not snapshot.get("feed", {}).get("polymarket", {}).get("connected", False):
                    reasons.append("POLYMARKET_FEED_DOWN")
                if not snapshot.get("feed", {}).get("binance", {}).get(asset, {}).get("connected", False):
                    reasons.append("BINANCE_FEED_DOWN")
                if snapshot.get("xrp", {}).get("news_blackout_active", False) and asset == "XRP":
                    reasons.append("NEWS_BLACKOUT_ACTIVE")
                regime = snapshot.get("bot", {}).get("current_regime", "RANGING")
                reasons.append(f"REGIME:{regime}")
                reasons.append(f"DEGRADATION:{snapshot.get('degradation_level', 0)}")
                await bus.publish(
                    "COVERAGE_FAILURE",
                    {"asset": asset, "gap_minutes": round(gap / 60, 2), "misses": count, "reasons": reasons},
                )
        coverage["last_attempt"] = last_attempt
        coverage["misses"] = misses
        coverage["threshold_relax"] = relax
        await self.state.set("coverage", value=coverage)
