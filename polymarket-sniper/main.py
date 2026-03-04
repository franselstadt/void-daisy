"""Main orchestration for polymarket autonomous profit engine."""

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
from intelligence.bayesian_updater import BayesianUpdater
from intelligence.continuous_learner import ContinuousLearner
from intelligence.thought_train import ThoughtTrain
from learning.trade_logger import TradeLogger
from regime.detector import RegimeDetector
from reporting.metrics import Metrics
from reporting.telegram import TelegramReporter
from risk.degrader import Degrader
from risk.monitor import CoverageMonitor, RiskMonitor
from signals.correlation import CorrelationEngine
from signals.exhaustion import ExhaustionScorer
from strategies.engine_manager import EngineManager
from strategies.window_scheduler import WindowScheduler
from trading.executor import TradeExecutor
from trading.guardian import TradeGuardian
from trading.position_manager import PositionManager
from trading.profit_taker import ProfitTaker
from trading.ranker import OpportunityRanker
from trading.sizing import calculate_bet_size


async def _health_check_loop(state: AppState, reporter: TelegramReporter) -> None:
    while True:
        snapshot = await state.snapshot()
        now = time.time()
        for name, data in snapshot.get("feed", {}).items():
            if isinstance(data, dict) and "connected" in data and (not data.get("connected", False)):
                if now - float(data.get("last_seen", now)) > 60:
                    await reporter.send_message(f"Feed disconnected >60s: {name}")
        await asyncio.sleep(10)


async def _hourly_report_loop(state: AppState, reporter: TelegramReporter, metrics: Metrics) -> None:
    while True:
        await asyncio.sleep(3600)
        snap = await state.snapshot()
        asset = metrics.summary()
        strategy = metrics.strategy_summary()
        lines = [f"🦞 HOURLY REPORT — {datetime.now(timezone.utc).strftime('%H:%M UTC')}", ""]
        for a in ["BTC", "ETH", "SOL", "XRP"]:
            row = asset.get(a, {"trades": 0, "wins": 0, "losses": 0, "pnl": 0.0})
            lines.append(f"{a} | {row['trades']} trades | {row['wins']}W {row['losses']}L | ${row['pnl']:.2f}")
        lines.extend(["", "Strategy breakdown:"])
        for s, row in strategy.items():
            wr = (row["wins"] / max(1, row["trades"])) * 100
            lines.append(f"{s}: {row['wins']}/{row['trades']} ({wr:.0f}%) | ${row['pnl']:.2f}")
        bankroll = float(snap.get("bankroll", 0.0))
        starting = float(snap.get("starting_bankroll", max(bankroll, 1.0)))
        perf = (bankroll - starting) / max(starting, 1e-9)
        lines.append(f"\nBankroll: ${bankroll:.2f} ({perf:+.1%})")
        lines.append(f"Win Rate: {float(snap.get('win_rate_10', 0.5)):.1%} | Mode: {snap.get('degradation_level', 0)}")
        lines.append(f"Regime: {snap.get('bot', {}).get('current_regime', 'RANGING')}")
        coverage = snap.get("coverage", {}).get("window_stats", {})
        if coverage:
            cov_line = []
            for a in ["BTC", "ETH", "SOL", "XRP"]:
                row = coverage.get(a, {"covered": 0, "total": 0})
                pct = (float(row.get("covered", 0)) / max(1, float(row.get("total", 0)))) * 100
                cov_line.append(f"{a} {pct:.0f}%")
            lines.append(f"Window coverage: {' | '.join(cov_line)}")
        await reporter.send_message("\n".join(lines))


async def _stats_update_loop(state: AppState) -> None:
    while True:
        snapshot = await state.snapshot()
        stats = snapshot.get("stats", {})
        stats["open_exposure"] = round(sum(float(p.get("bet_size", 0.0)) for p in snapshot.get("open_positions", {}).values()), 4)
        await state.set("stats", value=stats)
        await asyncio.sleep(30)


async def main() -> None:
    load_dotenv()
    os.chdir(os.path.dirname(__file__) or ".")
    configure_logger()

    state = AppState()
    bankroll = float(os.getenv("STARTING_BANKROLL", "200.0"))
    await state.set("bankroll", value=bankroll)
    await state.set("starting_bankroll", value=bankroll)
    await state.set("high_watermark_bankroll", value=bankroll)

    config = ConfigManager("data/config.json")
    config.start_watching()
    exhaustion = ExhaustionScorer("data/signal_weights.json")
    exhaustion.start_watching()

    trade_logger = TradeLogger("data/trades.db")
    await trade_logger.init()
    metrics = Metrics()
    reporter = TelegramReporter(state, trade_logger, metrics)
    degrader = Degrader()
    guardian = TradeGuardian(state, config)
    executor = TradeExecutor(state)
    ranker = OpportunityRanker()
    position_manager = PositionManager(state)
    profit_taker = ProfitTaker(state)
    feed_manager = FeedManager(state)
    correlation_engine = CorrelationEngine(state)
    regime_detector = RegimeDetector(state)
    engine_manager = EngineManager(state, exhaustion)
    learner = ContinuousLearner(state, config, trade_logger)
    beliefs = BayesianUpdater(state)
    thought_train = ThoughtTrain(state, config, trade_logger)
    risk_monitor = RiskMonitor(state, degrader)
    coverage_monitor = CoverageMonitor(state)
    window_scheduler = WindowScheduler(state, engine_manager)

    async def on_opportunity(opportunity: dict[str, Any]) -> None:
        bot = await state.get("bot", default={})
        if bot.get("emergency_stopped") or bot.get("hard_stopped") or bot.get("paused"):
            return
        stats = await state.get("stats", default={})
        stats["opportunities_seen"] = int(stats.get("opportunities_seen", 0)) + 1
        await state.set("stats", value=stats)

        snapshot = await state.snapshot()
        ranked = ranker.rank([opportunity], snapshot)
        if not ranked:
            return
        chosen = ranked[0]

        profile = degrader.profile(int(snapshot.get("degradation_level", 0)))
        if chosen.get("strategy") not in profile.get("active_strategies", []):
            await bus.publish("TRADE_BLOCKED", {"asset": chosen.get("asset"), "reason": "strategy_paused_by_degradation", "strategy": chosen.get("strategy")})
            return

        strategy = str(chosen.get("strategy", "EXHAUSTION_SNIPER"))
        win_rate_by_strategy = snapshot.get("stats", {}).get("win_rate_10", {})
        strategy_wr = float(win_rate_by_strategy.get(strategy, snapshot.get("win_rate_10", 0.5)))
        bet_size = calculate_bet_size(
            bankroll=float(snapshot.get("bankroll", 0.0)),
            entry_price=float(chosen.get("entry_price", 0.5)),
            confidence=float(chosen.get("confidence", 0.5)),
            win_rate_10=strategy_wr,
            consecutive_losses=int(snapshot.get("consecutive_losses", 0)),
            asset=str(chosen.get("asset", "BTC")),
            strategy=strategy,
            degradation_level=int(snapshot.get("degradation_level", 0)),
            open_exposure=float(snapshot.get("stats", {}).get("open_exposure", 0.0)),
        )
        chosen["bet_size"] = max(1.0, float(bet_size))

        allowed, reason = await guardian.check(chosen, profile)
        if not allowed:
            stats = await state.get("stats", default={})
            stats["opportunities_blocked"] = int(stats.get("opportunities_blocked", 0)) + 1
            blocks = stats.setdefault("guardian_blocks", {}).setdefault(str(chosen.get("asset", "UNK")), [])
            blocks.append(reason)
            stats["guardian_blocks"][str(chosen.get("asset", "UNK"))] = blocks[-20:]
            await state.set("stats", value=stats)
            await bus.publish("TRADE_BLOCKED", {"asset": chosen.get("asset"), "reason": reason, "strategy": strategy})
            return

        await coverage_monitor.record_attempt(str(chosen.get("asset", "BTC")))
        await window_scheduler.record_attempt(str(chosen.get("asset", "BTC")))
        result = await executor.enter_trade(chosen, chosen["bet_size"])
        if not result.success:
            logger.warning("entry_failed", strategy=strategy, error=result.error)
            return

        stats = await state.get("stats", default={})
        stats["opportunities_taken"] = int(stats.get("opportunities_taken", 0)) + 1
        await state.set("stats", value=stats)

    async def on_trade_exit_request(event: dict[str, Any]) -> None:
        await executor.exit_trade(event, str(event.get("reason", "EXIT")))

    async def on_trade_exited(event: dict[str, Any]) -> None:
        row = dict(event)
        row.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
        row.setdefault("signals_fired", list((row.get("signal_scores") or {}).keys()))
        row.setdefault("bankroll_at_entry", await state.get("bankroll", default=0.0))
        row.setdefault("win_rate_10_at_entry", await state.get("win_rate_10", default=0.5))
        row.setdefault("consecutive_losses_at_entry", await state.get("consecutive_losses", default=0))
        row.setdefault("regime_at_entry", await state.get("bot", "current_regime", default="RANGING"))
        row.setdefault("degradation_level_at_entry", await state.get("degradation_level", default=0))
        await trade_logger.log_trade(row)

    async def on_thought_train_complete(event: dict[str, Any]) -> None:
        await trade_logger.log_thought_train(event)

    bus.subscribe("OPPORTUNITY_DETECTED", on_opportunity)
    bus.subscribe("SCHEDULED_OPPORTUNITY", on_opportunity)
    bus.subscribe("TRADE_EXIT_REQUEST", on_trade_exit_request)
    bus.subscribe("TRADE_EXITED", on_trade_exited)
    bus.subscribe("THOUGHT_TRAIN_COMPLETED", on_thought_train_complete)

    await asyncio.gather(
        bus.run(),
        start_binance_feeds(state),
        PolymarketFeed(state).run(),
        start_chainlink_feed(state),
        regime_detector.run(),
        engine_manager.run(),
        learner.run(),
        beliefs.run(),
        thought_train.run(),
        risk_monitor.run(),
        coverage_monitor.run(),
        reporter.run(),
        window_scheduler.run(),
        profit_taker.run(),
        position_manager.run(),
        correlation_engine.run(),
        feed_manager.run(),
        _hourly_report_loop(state, reporter, metrics),
        _health_check_loop(state, reporter),
        _stats_update_loop(state),
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("shutdown_requested")
