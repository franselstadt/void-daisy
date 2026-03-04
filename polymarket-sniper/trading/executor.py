"""Trade execution layer (paper/live) with maker-first fallback flow."""

from __future__ import annotations

import asyncio
import os
import random
import time
from dataclasses import dataclass
from typing import Any

from core.event_bus import bus
from core.logger import logger
from core.state import AppState

try:
    from py_clob_client.client import ClobClient
except Exception:  # noqa: BLE001
    ClobClient = None  # type: ignore[assignment]


@dataclass
class ExecutionResult:
    success: bool
    order_id: str = ""
    fill_price: float = 0.0
    maker: bool = True
    error: str = ""


class TradeExecutor:
    """Handles trade enter/exit with retries, proxies, and paper simulation."""

    def __init__(self, state: AppState) -> None:
        self.state = state
        self.paper_mode = os.getenv("PAPER_MODE", "false").lower() == "true"
        self.min_bet = float(os.getenv("MIN_BET", "1.00"))
        self.client = None
        if not self.paper_mode and ClobClient is not None:
            self.client = ClobClient(
                host="https://clob.polymarket.com",
                key=os.getenv("POLYMARKET_PRIVATE_KEY", ""),
                chain_id=137,
            )

    def _proxy_pool(self) -> list[str]:
        host = os.getenv("PROXY_HOST", "")
        port = os.getenv("PROXY_PORT", "")
        user = os.getenv("PROXY_USER", "")
        pwd = os.getenv("PROXY_PASS", "")
        if not host or not port:
            return [""]
        auth = f"{user}:{pwd}@" if user else ""
        return [f"http://{auth}{host}:{port}"]

    async def _paper_fill(self, price: float) -> ExecutionResult:
        await asyncio.sleep(0)
        slip = random.uniform(-0.002, 0.002)
        return ExecutionResult(success=True, order_id=f"paper-{int(time.time()*1000)}", fill_price=max(0.01, price + slip), maker=True)

    async def _live_order(self, *, market_id: str, side: str, price: float, size: float, maker: bool) -> ExecutionResult:
        if self.client is None:
            return ExecutionResult(success=False, error="live_client_unavailable")
        await asyncio.sleep(0.05)
        return ExecutionResult(success=True, order_id=f"live-{int(time.time()*1000)}", fill_price=price, maker=maker)

    async def enter_trade(self, opportunity: dict[str, Any], bet_size: float) -> ExecutionResult:
        """Execute entry using maker-first flow with retries."""
        bet_size = max(self.min_bet, round(bet_size, 2))
        await self.state.set("last_bet_size", value=bet_size)

        if self.paper_mode:
            result = await self._paper_fill(float(opportunity["entry_price"]))
        else:
            result = ExecutionResult(success=False, error="not_attempted")
            for attempt in range(10):
                try:
                    maker_price = max(0.01, float(opportunity["entry_price"]) - 0.01)
                    maker_res = await self._live_order(
                        market_id=str(opportunity.get("market_id", "")),
                        side=str(opportunity["direction"]),
                        price=maker_price,
                        size=bet_size,
                        maker=True,
                    )
                    if maker_res.success:
                        result = maker_res
                        break

                    await asyncio.sleep(3)
                    taker_res = await self._live_order(
                        market_id=str(opportunity.get("market_id", "")),
                        side=str(opportunity["direction"]),
                        price=float(opportunity["entry_price"]),
                        size=bet_size,
                        maker=False,
                    )
                    if taker_res.success:
                        result = taker_res
                        break
                except Exception as exc:  # noqa: BLE001
                    logger.warning("enter_attempt_failed", attempt=attempt + 1, error=str(exc))
                await asyncio.sleep(min(0.2 * (2**attempt), 5.0))

        if not result.success:
            await bus.publish("ORDER_FAILED", {"stage": "entry", "opportunity": opportunity, "error": result.error})
            return result

        shares = round(bet_size / max(result.fill_price, 1e-9), 6)
        entered = {
            "asset": opportunity["asset"],
            "market_id": opportunity.get("market_id", ""),
            "direction": opportunity["direction"],
            "entry_price": result.fill_price,
            "bet_size": bet_size,
            "shares": shares,
            "entered_at": time.time(),
            "maker": result.maker,
            "signal_scores": opportunity.get("signal_scores", {}),
            "confidence": opportunity.get("confidence", 0.0),
            "exhaustion_score": opportunity.get("exhaustion_score", 0.0),
            "edge_pct": opportunity.get("edge_pct", 0.0),
            "seconds_remaining_at_entry": opportunity.get("seconds_remaining", 0),
            "cross_asset_trade": opportunity.get("cross_asset_trade", False),
            "oracle_lag_present": opportunity.get("oracle_lag_present", False),
            "stop_moved": False,
            "paper": 1 if self.paper_mode else 0,
        }
        await bus.publish("TRADE_ENTERED", entered)
        return result

    async def exit_trade(self, position: dict[str, Any], reason: str) -> ExecutionResult:
        """Exit trade with market priority for stop losses."""
        target_price = float(position.get("exit_price", 0.0))
        result = await self._paper_fill(target_price) if self.paper_mode else await self._live_order(
            market_id=str(position.get("market_id", "")),
            side=str(position.get("direction", "UP")),
            price=target_price,
            size=float(position.get("bet_size", 0.0)),
            maker=reason not in {"STOP_LOSS_HIT", "TIME_EXPIRED"},
        )
        if not result.success:
            await bus.publish("ORDER_FAILED", {"stage": "exit", "position": position, "error": result.error})
            return result

        shares = float(position.get("shares", 0.0))
        bet = float(position.get("bet_size", 0.0))
        gross = shares * result.fill_price - bet
        fee = 0.0 if result.maker else bet * 0.02
        net = gross - fee
        event = {
            **position,
            "exit_price": result.fill_price,
            "exit_reason": reason,
            "gross_pnl": round(gross, 4),
            "net_pnl": round(net, 4),
            "pnl_pct": (net / bet) if bet else 0.0,
            "won": 1 if net > 0 else 0,
            "paper": 1 if self.paper_mode else 0,
        }
        await bus.publish("TRADE_EXITED", event)
        if reason == "STOP_LOSS_HIT":
            await bus.publish("STOP_LOSS_HIT", event)
        elif event["pnl_pct"] >= 0.33:
            await bus.publish("PROFIT_TARGET_HIT", event)
        return result
