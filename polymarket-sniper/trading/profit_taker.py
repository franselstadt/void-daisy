"""Tick-by-tick position exit logic with per-strategy behavior."""

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

    def _momentum_reversal(self, direction: str, tick: dict[str, Any], threshold: float = 0.001) -> bool:
        v10 = float(tick.get("velocity_10s", 0.0))
        return (direction == "UP" and v10 < -threshold) or (direction == "DOWN" and v10 > threshold)

    def _trailing_hit(self, position: dict[str, Any], current_price: float, trail_pct: float) -> bool:
        high = float(position.get("high_watermark_price", position.get("entry_price", current_price)))
        return current_price <= high * (1.0 - trail_pct)

    def _resolve_reason(self, position: dict[str, Any], tick: dict[str, Any], pnl_pct: float, current_price: float, seconds_remaining: int) -> str | None:
        strategy = str(position.get("strategy", "EXHAUSTION_SNIPER"))
        direction = str(position.get("direction", "UP"))
        entry_price = float(position.get("entry_price", current_price))

        # Universal hard stop.
        if current_price <= 0.02:
            return "STOP_LOSS_HIT"

        if strategy == "EXHAUSTION_SNIPER":
            if seconds_remaining <= 30:
                return "TIME_30S"
            if seconds_remaining <= 60 and pnl_pct > 0:
                return "TIME_60S_PROFIT"
            if self._momentum_reversal(direction, tick) and pnl_pct > 0:
                return "MOMENTUM_REVERSAL"
            if pnl_pct >= 0.85:
                return "TAKE_85"
            if pnl_pct >= 0.33:
                threshold = 3 if pnl_pct < 0.5 else 4 if pnl_pct < 0.7 else 5
                if self._green_signals(position, tick) < threshold:
                    return "TAKE_PROFIT"
            if position.get("stop_moved", False) and current_price <= entry_price:
                return "BREAKEVEN_STOP"
            return None

        if strategy == "MOMENTUM_RIDER":
            if seconds_remaining <= 45:
                return "TIME_45S"
            if seconds_remaining <= 90 and pnl_pct < 0.15:
                return "TIME_90S_SMALL"
            if float(tick.get("volume_ratio_10_60", tick.get("volume_ratio", 1.0))) < 0.5:
                return "VOLUME_DROPS"
            if float(tick.get("spread", 0.0)) > 0.06:
                return "SPREAD_WIDENS"
            if pnl_pct >= 0.20 and self._trailing_hit(position, current_price, 0.12):
                return "TRAILING_STOP"
            if self._momentum_reversal(direction, tick, threshold=0.0008):
                return "VELOCITY_REVERSAL"
            if pnl_pct >= 0.75:
                return "TARGET_REACHED"
            return None

        if strategy == "ORACLE_ARB":
            if bool(tick.get("oracle_updated", False)):
                return "ORACLE_UPDATED"
            if float(tick.get("lag_score", 1.0)) < 0.02:
                return "LAG_RESOLVED"
            if self._momentum_reversal(direction, tick, threshold=0.0006):
                return "VELOCITY_REVERSAL"
            if seconds_remaining <= 30:
                return "TIME_30S"
            if pnl_pct >= 0.35:
                return "TARGET_ARB"
            return None

        if strategy == "MEAN_REVERSION":
            move_away = abs(current_price - 0.5) - abs(entry_price - 0.5)
            if move_away > 0.05:
                return "EXTENDS_AWAY"
            if pnl_pct >= 0.25:
                return "TARGET_REACHED"
            if pnl_pct >= 0.15 and self._trailing_hit(position, current_price, 0.10):
                return "TRAILING_STOP"
            if abs(float(tick.get("velocity_60s", 0.0))) > 0.001:
                return "VELOCITY_SURGES"
            if seconds_remaining <= 60 and pnl_pct > 0:
                return "TIME_60S_PROFIT"
            if seconds_remaining <= 30:
                return "TIME_30S"
            return None

        if strategy == "CROSS_ASSET_LAG":
            if float(tick.get("lag_score", 1.0)) < 0.02:
                return "LAG_RESOLVED"
            if bool(tick.get("btc_reversal", False)):
                return "BTC_REVERSAL"
            if float(tick.get("elapsed_since_anchor", 0.0)) > float(tick.get("correlation_lag", 10.0)) * 3:
                return "LAG_TIMER"
            if pnl_pct >= 0.25:
                return "TARGET_REACHED"
            if seconds_remaining <= 30:
                return "TIME_30S"
            return None

        return None

    async def on_tick(self, event: dict[str, Any]) -> None:
        """Evaluate each position and emit TRADE_EXIT_REQUEST if condition triggers."""
        asset = event.get("asset")
        oracle = await self.state.get("oracle", asset, default={})
        event = {
            **event,
            "oracle_updated": (float(oracle.get("last_update_timestamp", 0.0)) + 1.0) >= float(event.get("timestamp", 0.0)),
            "correlation_lag": float((await self.state.get("correlation_lag", default={})).get(asset, 10.0)),
        }
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

        position["high_watermark_price"] = max(float(position.get("high_watermark_price", entry_price)), current_price)
        positions[asset] = position
        await self.state.set("open_positions", value=positions)
        if pnl_pct >= 0.33 and not position.get("stop_moved", False):
            position["stop_moved"] = True
            positions[asset] = position
            await self.state.set("open_positions", value=positions)

        reason = self._resolve_reason(position, event, pnl_pct, current_price, seconds_remaining)

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
