"""OpenClaw runtime entry for Polymarket Profit Engine."""

from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, timezone

import aiosqlite
from dotenv import load_dotenv

from core.config import config
from core.event_bus import bus
from core.logger import setup_logging
from core.state import state
from feeds.binance_ws import start_binance_feeds
from feeds.chainlink_feed import start_chainlink_feed
from feeds.polymarket_ws import PolymarketFeed
from learning.coordinator import LearningCoordinator
from plans.engine_manager import EngineManager
from regime.detector import RegimeDetector
from reporting.telegram import TelegramReporter
from risk.degrader import LEVELS
from risk.monitor import RiskMonitor
from risk.thought_train import ThoughtTrain
from scheduler.coverage_monitor import CoverageMonitor
from scheduler.window_scheduler import WindowScheduler
from signals.correlation import CorrelationTracker
from trading.executor import executor
from trading.guardian import check as guardian_check
from trading.profit_taker import run_profit_taker
from trading.ranker import rank
from trading.sizing import calculate_bet_size

CREATE_TRADES = (
    "CREATE TABLE IF NOT EXISTS trades ("
    "id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL, asset TEXT NOT NULL, market_id TEXT, "
    "strategy TEXT NOT NULL, direction TEXT NOT NULL, entry_price REAL, exit_price REAL, exit_reason TEXT, "
    "bet_size REAL, shares REAL, gross_pnl REAL, net_pnl REAL, pnl_pct REAL, won INTEGER, held_past_33 INTEGER, "
    "extra_gain REAL, exhaustion_score REAL, confidence REAL, edge_pct REAL, signals_fired TEXT, signal_scores TEXT, "
    "seconds_remaining_at_entry INTEGER, bankroll_at_entry REAL, win_rate_10_at_entry REAL, consecutive_losses_at_entry INTEGER, "
    "regime_at_entry TEXT, degradation_level_at_entry INTEGER, oracle_lag_present INTEGER, cross_asset_trade INTEGER, "
    "maker_fill INTEGER, paper INTEGER DEFAULT 0)"
)
CREATE_THOUGHT = (
    "CREATE TABLE IF NOT EXISTS thought_trains ("
    "id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, trigger_reason TEXT, loss_pattern TEXT, "
    "root_cause TEXT, regime_at_time TEXT, changes_made TEXT, success INTEGER, "
    "win_rate_before REAL, win_rate_after_5_trades REAL)"
)
CREATE_WEIGHTS = (
    "CREATE TABLE IF NOT EXISTS weight_updates ("
    "id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, trigger TEXT, old_win_rate REAL, "
    "new_win_rate REAL, improvement REAL, changes TEXT)"
)
CREATE_REGIME = (
    "CREATE TABLE IF NOT EXISTS regime_log ("
    "id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, regime TEXT, trend_score REAL, "
    "volatility_ratio REAL, correlation_score REAL, duration_seconds INTEGER, pnl_during_regime REAL, best_strategy TEXT)"
)


async def init_database(path: str = "data/trades.db") -> None:
    os.makedirs("data", exist_ok=True)
    async with aiosqlite.connect(path) as db:
        await db.execute(CREATE_TRADES)
        await db.execute(CREATE_THOUGHT)
        await db.execute(CREATE_WEIGHTS)
        await db.execute(CREATE_REGIME)
        await db.commit()


async def log_trade(row: dict, path: str = "data/trades.db") -> None:
    query = (
        "INSERT INTO trades (timestamp, asset, market_id, strategy, direction, entry_price, exit_price, "
        "exit_reason, bet_size, shares, gross_pnl, net_pnl, pnl_pct, won, held_past_33, extra_gain, exhaustion_score, "
        "confidence, edge_pct, signals_fired, signal_scores, seconds_remaining_at_entry, bankroll_at_entry, "
        "win_rate_10_at_entry, consecutive_losses_at_entry, regime_at_entry, degradation_level_at_entry, "
        "oracle_lag_present, cross_asset_trade, maker_fill, paper) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
    )
    async with aiosqlite.connect(path) as db:
        await db.execute(
            query,
            (
                row.get("timestamp"),
                row.get("asset"),
                row.get("market_id"),
                row.get("plan"),
                row.get("direction"),
                row.get("entry_price"),
                row.get("exit_price"),
                row.get("reason", row.get("exit_reason")),
                row.get("bet_size"),
                row.get("shares"),
                row.get("gross_pnl", 0.0),
                row.get("net_pnl", 0.0),
                row.get("pnl_pct", 0.0),
                row.get("won", 0),
                row.get("held_past_33", 0),
                row.get("extra_gain", 0.0),
                row.get("exhaustion_score", 0.0),
                row.get("confidence", 0.0),
                row.get("edge_pct", 0.0),
                str(row.get("signals_fired", [])),
                str(row.get("signal_scores", {})),
                row.get("seconds_remaining", row.get("seconds_remaining_at_entry", 0)),
                row.get("bankroll_at_entry", 0.0),
                row.get("win_rate_10_at_entry", 0.0),
                row.get("consecutive_losses_at_entry", 0),
                row.get("regime_at_entry", "RANGING"),
                row.get("degradation_level_at_entry", 0),
                int(bool(row.get("oracle_lag_present", False))),
                int(bool(row.get("cross_asset_trade", False))),
                int(bool(row.get("maker_fill", False))),
                row.get("paper", 0),
            ),
        )
        await db.commit()


async def hourly_report(reporter: TelegramReporter) -> None:
    while True:
        await asyncio.sleep(3600)
        bankroll = float(state.get('stats.bankroll', state.get('bankroll', 0.0)))
        pnl_hour = float(state.get("stats.pnl_this_hour", 0.0))
        pnl_session = float(state.get("stats.pnl_session", 0.0))
        wr10 = float(state.get("stats.win_rate_10", 0.5))
        wr20 = float(state.get("stats.win_rate_20", 0.5))
        dd = float(state.get("stats.drawdown_pct", 0.0))
        trades = int(state.get("stats.trades_this_session", 0))
        level = int(state.get("bot.degradation_level", 0))
        mode = LEVELS.get(level, {}).get("name", "NORMAL")
        regime = state.get("bot.current_regime", "RANGING")
        paper = "PAPER" if state.get("bot.paper_mode", True) else "LIVE"
        tt_active = "YES" if state.get("bot.thought_train_active", False) else "no"

        lines = [f"🦞 HOURLY REPORT — {datetime.now(timezone.utc).strftime('%H:%M UTC')}"]
        lines.append(f"Mode: {paper} | {mode} (L{level}) | Regime: {regime}")
        lines.append(f"Bankroll: ${bankroll:.2f} | Drawdown: {dd:.1%}")
        lines.append(f"PnL: hour ${pnl_hour:+.2f} | session ${pnl_session:+.2f}")
        lines.append(f"Win Rate: {wr10:.0%} (10) | {wr20:.0%} (20) | Trades: {trades}")
        lines.append(f"Thought Train: {tt_active}")
        for asset in ["BTC", "ETH", "SOL", "XRP"]:
            covered = int(state.get(f'coverage.window_covered.{asset}', 0))
            total = int(state.get(f'coverage.window_total.{asset}', 0))
            pct = f"{covered/total*100:.0f}%" if total else "0%"
            lines.append(f"  {asset} coverage {pct} ({covered}/{total})")
        await reporter.send("\n".join(lines))
        state.set_sync("stats.pnl_this_hour", 0.0)


def _ensure_data_files() -> None:
    """Create default data files if missing — required for cold starts."""
    import json as _json
    from pathlib import Path as _P
    _P("data/versions").mkdir(parents=True, exist_ok=True)
    _P("logs").mkdir(parents=True, exist_ok=True)
    defaults = {
        "data/config.json": {"version": 1},
        "data/signal_weights.json": {},
        "data/bayesian_beliefs.json": {},
        "data/bandit_state.json": {},
        "data/rl_sizer_state.json": {"q_table": {}, "epsilon": 0.1, "multiplier": 1.0},
        "data/correlation_state.json": {
            "lag": {"ETH": 8.0, "SOL": 12.0, "XRP": 15.0},
            "strength": {"ETH": 0.8, "SOL": 0.75, "XRP": 0.6},
        },
    }
    for path, default in defaults.items():
        p = _P(path)
        if not p.exists():
            p.write_text(_json.dumps(default, indent=2))


def _load_persistent_state() -> None:
    """Reload persisted learning state from data/*.json into state."""
    import json as _json
    from pathlib import Path as _P
    try:
        data = _json.loads(_P("data/correlation_state.json").read_text())
        for asset in ["ETH", "SOL", "XRP"]:
            state.set_sync(f"correlation.lag.{asset}", float(data.get("lag", {}).get(asset, 10.0)))
            state.set_sync(f"correlation.strength.{asset}", float(data.get("strength", {}).get(asset, 0.7)))
    except Exception:
        pass
    try:
        beliefs = _json.loads(_P("data/bayesian_beliefs.json").read_text())
        if beliefs:
            state.set_sync("learning.l1.beliefs", beliefs)
    except Exception:
        pass
    try:
        rl = _json.loads(_P("data/rl_sizer_state.json").read_text())
        state.set_sync("learning.l7.rl_sizer.multiplier", float(rl.get("multiplier", 1.0)))
    except Exception:
        pass


async def main() -> None:
    load_dotenv()
    os.chdir(os.path.dirname(__file__) or ".")
    setup_logging()

    _ensure_data_files()
    config.start()
    await init_database()

    _load_persistent_state()
    start_bankroll = float(os.getenv("STARTING_BANKROLL", "200.0"))
    state.set_sync("stats.bankroll", start_bankroll)
    state.set_sync("bankroll", start_bankroll)
    state.set_sync("stats.session_start_bankroll", start_bankroll)
    state.set_sync("stats.high_watermark", start_bankroll)
    state.set_sync("bot.current_regime", "RANGING")
    state.set_sync("bot.degradation_level", 0)
    state.set_sync("bot.emergency_stopped", False)
    state.set_sync("bot.hard_stopped", False)
    state.set_sync("bot.paused", False)
    state.set_sync("bot.paper_mode", os.getenv("PAPER_MODE", "true").lower() == "true")
    state.set_sync("bot.session_start", time.time())
    for asset in ["BTC", "ETH", "SOL", "XRP"]:
        state.set_sync(f"coverage.last_attempt.{asset}", 0.0)
        state.set_sync(f"coverage.window_covered.{asset}", 0)
        state.set_sync(f"coverage.window_total.{asset}", 0)
        state.set_sync(f"coverage.misses.{asset}", 0)
        state.set_sync(f"coverage.threshold_relax.{asset}", 1.0)

    engine_manager = EngineManager()
    scheduler = WindowScheduler(engine_manager)
    coverage = CoverageMonitor()
    reporter = TelegramReporter()

    async def on_opportunity(opp: dict) -> None:
        if state.get("bot.emergency_stopped", False) or state.get("bot.hard_stopped", False) or state.get("bot.paused", False):
            return
        selected = rank([opp])[0]
        state.set_sync("stats.opportunities_seen", int(state.get("stats.opportunities_seen", 0)) + 1)

        bankroll = float(state.get("stats.bankroll", state.get("bankroll", 0.0)))
        plan = str(selected.get("plan", "PLAN_01"))
        wr10 = float(state.get(f"stats.win_rate_10.{plan}", state.get("stats.win_rate_10", 0.5)))
        level = int(state.get("bot.degradation_level", 0))
        temp_mult = float(state.get("trading.temp_size_mult", 1.0))
        bet = calculate_bet_size(
            bankroll=bankroll,
            entry_price=float(selected.get("entry_price", 0.5)),
            confidence=float(selected.get("confidence", 0.5)),
            win_rate_10=wr10,
            consecutive_losses=int(state.get("stats.consecutive_losses", 0)),
            asset=str(selected.get("asset", "BTC")),
            plan=plan,
            degradation_level=level,
        )
        selected["bet_size"] = max(1.0, round(bet * temp_mult, 2))

        ok, reason = guardian_check(selected)
        if not ok:
            state.append_list(f"stats.guardian_blocks.{selected.get('asset')}", reason, maxlen=20)
            state.set_sync("stats.opportunities_blocked", int(state.get("stats.opportunities_blocked", 0)) + 1)
            await bus.publish("TRADE_BLOCKED", {"asset": selected.get("asset"), "plan": plan, "reason": reason})
            return

        scheduler.record_attempt(str(selected["asset"]))
        state.set_sync(f"coverage.last_attempt.{selected['asset']}", time.time())
        result = await executor.enter_trade(selected)
        if result.success:
            state.set_sync("stats.opportunities_taken", int(state.get("stats.opportunities_taken", 0)) + 1)

    async def on_exit_request(req: dict) -> None:
        req['bankroll_before_exit'] = float(state.get('stats.bankroll', state.get('bankroll', 0.0)))
        await executor.exit_trade(req)

    async def on_trade_exited(evt: dict) -> None:
        row = dict(evt)
        row["timestamp"] = datetime.now(timezone.utc).isoformat()
        row["bankroll_at_entry"] = float(evt.get("bankroll_before_exit", state.get("stats.bankroll", 0.0)))
        row["win_rate_10_at_entry"] = float(state.get("stats.win_rate_10", 0.5))
        row["consecutive_losses_at_entry"] = int(state.get("stats.consecutive_losses", 0))
        row["regime_at_entry"] = state.get("bot.current_regime", "RANGING")
        row["degradation_level_at_entry"] = int(state.get("bot.degradation_level", 0))
        row.setdefault("signals_fired", [])
        row.setdefault("signal_scores", {})
        plan = str(row.get("plan", "PLAN_01"))
        seq10 = list(state.get(f"stats._plan_last10.{plan}", []))
        seq20 = list(state.get(f"stats._plan_last20.{plan}", []))
        won = int(row.get("won", 0))
        seq10.append(won)
        seq20.append(won)
        seq10 = seq10[-10:]
        seq20 = seq20[-20:]
        state.set_sync(f"stats._plan_last10.{plan}", seq10)
        state.set_sync(f"stats._plan_last20.{plan}", seq20)
        state.set_sync(f"stats.win_rate_10.{plan}", sum(seq10) / len(seq10) if seq10 else 0.5)
        state.set_sync(f"stats.win_rate_20.{plan}", sum(seq20) / len(seq20) if seq20 else 0.5)
        await log_trade(row)
        if row.get("reason") == "STOP_LOSS_HIT":
            await bus.publish("STOP_LOSS_HIT", row)

    bus.subscribe("OPPORTUNITY_DETECTED", on_opportunity)
    bus.subscribe("SCHEDULED_OPPORTUNITY", on_opportunity)
    bus.subscribe("TRADE_EXIT_REQUEST", on_exit_request)
    bus.subscribe("TRADE_EXITED", on_trade_exited)

    from core.logger import logger as _log

    tasks = [
        bus.run(),
        start_binance_feeds(),
        PolymarketFeed().run(),
        start_chainlink_feed(),
        RegimeDetector().run(),
        engine_manager.run(),
        LearningCoordinator().run(),
        ThoughtTrain().run(),
        RiskMonitor().run(),
        scheduler.run(),
        coverage.run(),
        run_profit_taker(),
        CorrelationTracker().run(),
        reporter.run(),
        hourly_report(reporter),
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            _log.error('task_failed', task_index=i, error=str(r))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
