"""Main orchestration for polymarket sniper bot."""

from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, timezone
from typing import Any

from dotenv import load_dotenv

from core.config import ConfigManager
from core.event_bus import bus
from core.logger import configure_logger, logger
from core.state import AppState
from feeds.binance_ws import start_binance_feeds
from feeds.chainlink_feed import start_chainlink_feed
from feeds.feed_manager import FeedManager
from feeds.polymarket_ws import PolymarketFeed
from learning.continuous_learner import ContinuousLearner
from learning.hot_updater import HotUpdater
from learning.trade_logger import TradeLogger
from reporting.metrics import Metrics
from reporting.telegram import TelegramReporter
from risk.degrader import Degrader
from risk.monitor import RiskMonitor
from signals.correlation import CorrelationEngine
from signals.exhaustion import ExhaustionScorer
from signals.signal_engine import SignalEngine
from trading.executor import TradeExecutor
from trading.guardian import TradeGuardian
from trading.position_manager import PositionManager
from trading.profit_taker import ProfitTaker
from trading.sizing import calculate_bet_size


async def _health_check_loop(state: AppState, reporter: TelegramReporter) -> None:
    """Feed status monitor that only warns and alerts."""
    while True:
        snapshot = await state.snapshot()
        feed = snapshot.get("feed", {})
        now = time.time()
        for name, data in feed.items():
            if isinstance(data, dict) and "connected" in data:
                if not data.get("connected", False) and now - float(data.get("last_seen", now)) > 60:
                    await reporter.send_message(f"Feed disconnected >60s: {name}")
        await asyncio.sleep(10)


async def _hourly_report_loop(state: AppState, reporter: TelegramReporter, metrics: Metrics) -> None:
    """Hourly operator report message."""
    while True:
        await asyncio.sleep(3600)
        snap = await state.snapshot()
        summary = metrics.summary()
        lines = ["🦞 HOURLY REPORT"]
        for asset in ["BTC", "ETH", "SOL", "XRP"]:
            row = summary.get(asset, {"trades": 0, "wins": 0, "losses": 0, "pnl": 0.0})
            lines.append(f"{asset} | {row['trades']} trades | {row['wins']}W {row['losses']}L | ${row['pnl']:.2f}")
        bankroll = float(snap.get("bankroll", 0.0))
        starting = float(snap.get("starting_bankroll", max(bankroll, 1.0)))
        perf = (bankroll - starting) / max(starting, 1e-9)
        lines.append(f"Bankroll: ${bankroll:.2f} ({perf:+.1%})")
        lines.append(f"Win Rate 10: {float(snap.get('win_rate_10', 0.0)):.1%} | Mode: {snap.get('degradation_level', 0)}")
        await reporter.send_message("\n".join(lines))


async def main() -> None:
    """Run all bot components concurrently and forever."""
    load_dotenv()
    os.chdir(os.path.dirname(__file__) or ".")
    configure_logger()

    state = AppState()
    starting_bankroll = float(os.getenv("STARTING_BANKROLL", "200.0"))
    await state.set("bankroll", value=starting_bankroll)
    await state.set("starting_bankroll", value=starting_bankroll)

    config = ConfigManager("data/config.json")
    config.start_watching()
    exhaustion = ExhaustionScorer("data/signal_weights.json")
    exhaustion.start_watching()

    trade_logger = TradeLogger("data/trades.db")
    await trade_logger.init()

    degrader = Degrader()
    metrics = Metrics()
    reporter = TelegramReporter(state, trade_logger, metrics)
    executor = TradeExecutor(state)
    guardian = TradeGuardian(state, config)

    signal_engine = SignalEngine(state, config, exhaustion)
    profit_taker = ProfitTaker(state)
    position_manager = PositionManager(state)
    learner = ContinuousLearner(state, config, trade_logger, HotUpdater())
    risk_monitor = RiskMonitor(state, degrader)
    feed_manager = FeedManager(state)
    correlation_engine = CorrelationEngine(state)

    async def on_snipe_opportunity(opportunity: dict[str, Any]) -> None:
        bot = await state.get("bot", default={})
        if bot.get("emergency_stopped") or bot.get("hard_stopped") or bot.get("paused"):
            return

        level = int(await state.get("degradation_level", default=0))
        profile = degrader.profile(level)

        bankroll = float(await state.get("bankroll", default=0.0))
        win_rate_10 = float(await state.get("win_rate_10", default=0.5))
        losses = int(await state.get("consecutive_losses", default=0))

        base_bet = calculate_bet_size(
            bankroll=bankroll,
            entry_price=float(opportunity["entry_price"]),
            confidence=float(opportunity["confidence"]),
            win_rate_10=win_rate_10,
            consecutive_losses=losses,
            asset=str(opportunity["asset"]),
        )
        bet_size = max(1.0, round(base_bet * float(profile["size_mult"]), 2))

        guarded = dict(opportunity)
        guarded["bet_size"] = bet_size
        allowed, reason = await guardian.check(guarded, profile)
        if not allowed:
            logger.info("trade_blocked", reason=reason, asset=opportunity.get("asset"))
            return

        res = await executor.enter_trade(opportunity, bet_size)
        if not res.success:
            logger.warning("entry_failed", asset=opportunity.get("asset"), error=res.error)

    async def on_trade_exit_request(event: dict[str, Any]) -> None:
        await executor.exit_trade(event, str(event.get("reason", "EXIT")))

    async def on_trade_exited(event: dict[str, Any]) -> None:
        row = dict(event)
        row.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
        row.setdefault("signals_fired", list((row.get("signal_scores") or {}).keys()))
        row.setdefault("bankroll_at_entry", await state.get("bankroll", default=0.0))
        row.setdefault("win_rate_10_at_entry", await state.get("win_rate_10", default=0.5))
        row.setdefault("consecutive_losses_at_entry", await state.get("consecutive_losses", default=0))
        row.setdefault("degradation_level", await state.get("degradation_level", default=0))
        await trade_logger.log_trade(row)

    bus.subscribe("SNIPE_OPPORTUNITY", on_snipe_opportunity)
    bus.subscribe("TRADE_EXIT_REQUEST", on_trade_exit_request)
    bus.subscribe("TRADE_EXITED", on_trade_exited)

    await asyncio.gather(
        bus.run(),
        start_binance_feeds(state),
        PolymarketFeed(state).run(),
        start_chainlink_feed(state),
        learner.run(),
        risk_monitor.run(),
        reporter.run(),
        signal_engine.run(),
        profit_taker.run(),
        position_manager.run(),
        correlation_engine.run(),
        feed_manager.run(),
        _health_check_loop(state, reporter),
        _hourly_report_loop(state, reporter, metrics),
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("shutdown_requested")
