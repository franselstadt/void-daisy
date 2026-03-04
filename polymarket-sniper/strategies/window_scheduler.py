"""Systematic 5-minute window participation scheduler."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

from core.event_bus import bus
from core.logger import logger
from core.state import AppState
from regime.fitness import get_engine_weight
from strategies.engine_manager import EngineManager


@dataclass
class WindowState:
    """Current Polymarket window state for one asset."""

    asset: str
    market_id: str
    opened_at: float
    seconds_elapsed: int
    seconds_remaining: int
    _zone_entry_time: float | None = None
    _in_zone: bool = False

    def has_been_in_zone_for(self, seconds: int, zone_min: int = 100, zone_max: int = 180) -> bool:
        """Return true only after staying in zone for at least N seconds."""
        currently = zone_min <= self.seconds_elapsed <= zone_max
        if currently and not self._in_zone:
            self._zone_entry_time = time.time()
            self._in_zone = True
        elif not currently:
            self._zone_entry_time = None
            self._in_zone = False
        return bool(self._zone_entry_time and (time.time() - self._zone_entry_time) >= seconds)


class WindowScheduler:
    """Ensures each asset window is systematically evaluated in prime zones."""

    WINDOW_DURATION = 300
    OPTIMAL_ENTRY_ZONES: dict[str, tuple[int, int]] = {
        "EXHAUSTION_SNIPER": (80, 190),
        "MOMENTUM_RIDER": (60, 160),
        "ORACLE_ARB": (0, 240),
        "MEAN_REVERSION": (90, 200),
        "CROSS_ASSET_LAG": (30, 220),
        "SCHEDULED": (100, 180),
    }

    def __init__(self, state: AppState, engine_manager: EngineManager) -> None:
        self.state = state
        self.engine_manager = engine_manager
        self.windows: dict[str, WindowState] = {}
        self.entry_attempted_this_window: dict[str, bool] = {"BTC": False, "ETH": False, "SOL": False, "XRP": False}

    async def record_attempt(self, asset: str) -> None:
        """Mark an asset as attempted in current window and update coverage state."""
        self.entry_attempted_this_window[asset] = True
        coverage = await self.state.get("coverage", default={})
        coverage.setdefault("last_attempt", {})
        coverage["last_attempt"][asset] = time.time()
        stats = coverage.setdefault("window_stats", {}).setdefault(asset, {"total": 0, "covered": 0, "current_market_id": ""})
        if stats.get("current_market_id") == self.windows.get(asset, WindowState(asset, "", 0, 0, 0)).market_id:
            stats["covered"] = int(stats.get("covered", 0)) + 1 if not stats.get("covered_marked", False) else int(stats.get("covered", 0))
            stats["covered_marked"] = True
        await self.state.set("coverage", value=coverage)

    async def run(self) -> None:
        """Track all windows every second and emit scheduled opportunities."""
        while True:
            await self._update_all_windows()
            await self._check_scheduled_entries()
            await asyncio.sleep(1)

    async def _update_all_windows(self) -> None:
        latest_poly = await self.state.get("latest_polymarket", default={})
        coverage = await self.state.get("coverage", default={})
        for asset in ["BTC", "ETH", "SOL", "XRP"]:
            poly = latest_poly.get(asset, {})
            if not poly:
                continue
            seconds_remaining = int(poly.get("seconds_remaining", 0))
            seconds_elapsed = max(0, self.WINDOW_DURATION - seconds_remaining)
            market_id = str(poly.get("market_id", ""))
            prev = self.windows.get(asset)
            if prev and prev.market_id != market_id:
                self.entry_attempted_this_window[asset] = False
                self.windows[asset] = WindowState(asset, market_id, time.time() - seconds_elapsed, seconds_elapsed, seconds_remaining)
            elif prev:
                prev.seconds_elapsed = seconds_elapsed
                prev.seconds_remaining = seconds_remaining
            else:
                self.windows[asset] = WindowState(asset, market_id, time.time() - seconds_elapsed, seconds_elapsed, seconds_remaining)

            stats = coverage.setdefault("window_stats", {}).setdefault(asset, {"total": 0, "covered": 0, "current_market_id": ""})
            if stats.get("current_market_id") != market_id:
                stats["total"] = int(stats.get("total", 0)) + 1
                stats["current_market_id"] = market_id
                stats["covered_marked"] = False
        await self.state.set("coverage", value=coverage)

    async def _check_scheduled_entries(self) -> None:
        for asset, window in self.windows.items():
            if self.entry_attempted_this_window.get(asset, False):
                continue
            if await self.state.get("open_positions", asset, default=None):
                continue
            zone_min, zone_max = self.OPTIMAL_ENTRY_ZONES["SCHEDULED"]
            if not (zone_min <= window.seconds_elapsed <= zone_max):
                continue
            if not window.has_been_in_zone_for(5, zone_min, zone_max):
                continue
            best = await self._find_best_opportunity(asset, window, relax_threshold=False)
            trigger = "WINDOW_SCHEDULER"
            if not best and window.seconds_elapsed >= 200 and window.seconds_remaining >= 80:
                best = await self._find_best_opportunity(asset, window, relax_threshold=True)
                trigger = "WINDOW_SCHEDULER_FORCED"
            if best:
                self.entry_attempted_this_window[asset] = True
                await bus.publish(
                    "SCHEDULED_OPPORTUNITY",
                    {
                        **best,
                        "trigger": trigger,
                        "window_elapsed": window.seconds_elapsed,
                        "window_remaining": window.seconds_remaining,
                    },
                )

    async def _find_best_opportunity(self, asset: str, window: WindowState, relax_threshold: bool = False) -> dict[str, Any] | None:
        poly_data = await self.state.get("latest_polymarket", asset, default={})
        if not poly_data:
            return None
        regime = str(await self.state.get("bot", "current_regime", default="RANGING"))
        threshold_relax = float((await self.state.get("coverage", "threshold_relax", default={})).get(asset, 1.0))
        candidates: list[dict[str, Any]] = []
        for name, engine in self.engine_manager.engines.items():
            fitness = get_engine_weight(name, regime)
            if fitness < 0.4 and not relax_threshold:
                continue
            try:
                opp = await engine.evaluate(poly_data, relax_threshold=(relax_threshold or threshold_relax < 1.0))
            except Exception as exc:  # noqa: BLE001
                logger.warning("window_scheduler_engine_error", engine=name, error=str(exc))
                continue
            if not opp:
                continue
            opp["effective_confidence"] = min(0.99, float(opp.get("confidence", 0.0)) / max(threshold_relax, 1e-9))
            elapsed = window.seconds_elapsed
            zmin, zmax = self.OPTIMAL_ENTRY_ZONES.get(name, (80, 190))
            timing_bonus = 1.08 if zmin <= elapsed <= zmax else 0.92
            opp["timing_bonus"] = timing_bonus
            opp["ev"] = float(opp.get("ev", opp.get("effective_confidence", opp.get("confidence", 0.0)))) * timing_bonus
            if relax_threshold:
                floor_conf = 0.55
                floor_exhaust = 2.5
                if float(opp.get("confidence", 0.0)) < floor_conf or float(opp.get("exhaustion_score", 0.0)) < floor_exhaust:
                    continue
            candidates.append(opp)
        if not candidates:
            return None
        return max(candidates, key=lambda x: float(x.get("ev", 0.0)))
