"""Orchestrates all strategy engines and publishes opportunities."""

from __future__ import annotations

import asyncio
from typing import Any

from core.event_bus import bus
from core.logger import logger
from core.state import AppState
from regime.fitness import get_active_engines
from signals.composer import SignalComposer
from signals.exhaustion import ExhaustionScorer
from strategies.cross_asset_lag import CrossAssetLagStrategy
from strategies.exhaustion_sniper import ExhaustionSniperStrategy
from strategies.mean_reversion import MeanReversionStrategy
from strategies.momentum_rider import MomentumRiderStrategy
from strategies.oracle_arb import OracleArbStrategy


class EngineManager:
    """Runs all engines and routes opportunities through event bus."""

    def __init__(self, state: AppState, exhaustion: ExhaustionScorer) -> None:
        self.state = state
        composer = SignalComposer(exhaustion)
        self.exhaustion_sniper = ExhaustionSniperStrategy(state, composer)
        self.momentum_rider = MomentumRiderStrategy(state, composer)
        self.oracle_arb = OracleArbStrategy(state, composer)
        self.mean_reversion = MeanReversionStrategy(state, composer)
        self.cross_asset_lag = CrossAssetLagStrategy(state, composer)
        self.engines = {
            self.exhaustion_sniper.name: self.exhaustion_sniper,
            self.momentum_rider.name: self.momentum_rider,
            self.oracle_arb.name: self.oracle_arb,
            self.mean_reversion.name: self.mean_reversion,
            self.cross_asset_lag.name: self.cross_asset_lag,
        }

    async def _emit_if_any(self, opportunity: dict[str, Any] | None) -> None:
        if not opportunity:
            return
        await bus.publish("OPPORTUNITY_DETECTED", opportunity)

    async def on_poly_tick(self, event: dict[str, Any]) -> None:
        """Evaluate applicable engines for each polymarket tick."""
        try:
            regime = str(await self.state.get("bot", "current_regime", default="RANGING"))
            active = set(get_active_engines(regime)) | {"EXHAUSTION_SNIPER"}
            for name in active:
                engine = self.engines.get(name)
                if engine:
                    await self._emit_if_any(await engine.evaluate(event))
        except Exception as exc:  # noqa: BLE001
            logger.warning("engine_manager_poly_error", error=str(exc))

    async def on_oracle_lag(self, event: dict[str, Any]) -> None:
        payload = dict(event)
        payload["type"] = "ORACLE_LAG_DETECTED"
        await self._emit_if_any(await self.oracle_arb.evaluate(payload))

    async def on_major_move(self, event: dict[str, Any]) -> None:
        await self.cross_asset_lag.on_major_move(event)

    async def run(self) -> None:
        """Subscribe strategy inputs and remain alive."""
        bus.subscribe("POLYMARKET_TICK", self.on_poly_tick)
        bus.subscribe("ORACLE_LAG_DETECTED", self.on_oracle_lag)
        bus.subscribe("MAJOR_MOVE", self.on_major_move)
        while True:
            await asyncio.sleep(3600)
