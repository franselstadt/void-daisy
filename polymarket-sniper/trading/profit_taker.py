"""Tick-by-tick position exit logic with momentum-aware profit holds."""

from __future__ import annotations

import asyncio
from typing import Any

from core.event_bus import bus
from core.state import AppState


class ProfitTaker:
    """Evaluates all open positions on every Polymarket tick (no I/O)."""

    def __init__(self, state: AppState) -> None:
        self.state = state

    @staticmethod
    def _hold_threshold(pnl_pct: float) -> int:
        if pnl_pct < 0.50:
            return 3
        if pnl_pct < 0.65:
            return 4
        if pnl_pct < 0.80:
            return 4
        if pnl_pct < 0.90:
            return 5
        return 99

    def _green_signals(self, position: dict[str, Any], tick: dict[str, Any]) -> int:
        direction = position["direction"]
        v10 = float(tick.get("velocity_10s", 0.0))
        v30 = float(tick.get("velocity_30s", 0.0))
        vol_ratio = float(tick.get("volume_ratio", 1.0))
        seconds_remaining = int(tick.get("seconds_remaining", 0))
        ob = tick.get("orderbook", {})
        bids = float(ob.get("bids_volume", 0.0))
        asks = float(ob.get("asks_volume", 0.0))

        score = 0
        if (direction == "UP" and v10 > 0) or (direction == "DOWN" and v10 < 0):
            score += 1
        if abs(v10) > abs(v30):
            score += 1
        if vol_ratio >= 0.8:
            score += 1
        if (direction == "UP" and bids >= asks) or (direction == "DOWN" and asks >= bids):
            score += 1
        if seconds_remaining > 90:
            score += 1
        return score

    async def on_tick(self, event: dict[str, Any]) -> None:
        """Evaluate each position and emit TRADE_EXIT_REQUEST if condition triggers."""
        asset = event.get("asset")
        positions = await self.state.get("open_positions", default={})
        if asset not in positions:
            return

        position = positions[asset]
        direction = position["direction"]
        current_price = float(event["yes_price"] if direction == "UP" else event["no_price"])
        bet_size = float(position["bet_size"])
        shares = float(position["shares"])
        entry_price = float(position["entry_price"])
        seconds_remaining = int(event.get("seconds_remaining", 0))
        pnl_pct = ((shares * current_price) - bet_size) / max(bet_size, 1e-9)

        reason = None

        if current_price <= 0.02:
            reason = "STOP_LOSS_HIT"
        elif seconds_remaining <= 30:
            reason = "TIME_EXPIRED"
        elif seconds_remaining <= 60 and pnl_pct > 0:
            reason = "TIME_PROFIT_LOCK"
        elif direction == "UP" and float(event.get("velocity_10s", 0.0)) < -0.001 and pnl_pct > 0:
            reason = "MOMENTUM_REVERSAL"
        elif direction == "DOWN" and float(event.get("velocity_10s", 0.0)) > 0.001 and pnl_pct > 0:
            reason = "MOMENTUM_REVERSAL"
        elif pnl_pct >= 0.90:
            reason = "TAKE_90_PLUS"
        elif pnl_pct >= 0.33:
            if not position.get("stop_moved", False):
                position["stop_moved"] = True
                positions[asset] = position
                await self.state.set("open_positions", value=positions)
            threshold = self._hold_threshold(pnl_pct)
            if self._green_signals(position, event) < threshold:
                reason = "TAKE_PROFIT"
        elif position.get("stop_moved", False) and current_price <= entry_price:
            reason = "BREAKEVEN_STOP"

        if reason:
            await bus.publish(
                "TRADE_EXIT_REQUEST",
                {
                    "asset": asset,
                    "market_id": position.get("market_id"),
                    "direction": direction,
                    "entry_price": entry_price,
                    "exit_price": current_price,
                    "shares": shares,
                    "bet_size": bet_size,
                    "reason": reason,
                    "seconds_remaining": seconds_remaining,
                    "pnl_pct": pnl_pct,
                    "signal_scores": position.get("signal_scores", {}),
                },
            )

    async def run(self) -> None:
        """Subscribe and keep alive."""
        bus.subscribe("POLYMARKET_TICK", self.on_tick)
        while True:
            await asyncio.sleep(3600)
