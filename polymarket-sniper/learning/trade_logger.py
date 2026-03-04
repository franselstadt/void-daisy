"""SQLite trade and optimisation logging."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import aiosqlite

SCHEMA = [
    """
CREATE TABLE IF NOT EXISTS trades (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  timestamp TEXT, asset TEXT, market_id TEXT,
  strategy TEXT, direction TEXT, entry_price REAL, exit_price REAL,
  exit_reason TEXT, bet_size REAL, shares REAL,
  gross_pnl REAL, net_pnl REAL, pnl_pct REAL,
  won INTEGER, held_past_33 INTEGER, extra_gain REAL,
  exhaustion_score REAL, confidence REAL, edge_pct REAL,
  signals_fired TEXT, signal_scores TEXT,
  seconds_remaining_at_entry INTEGER,
  bankroll_at_entry REAL, win_rate_10_at_entry REAL,
  consecutive_losses_at_entry INTEGER,
  regime_at_entry TEXT,
  degradation_level_at_entry INTEGER,
  oracle_lag_present INTEGER, cross_asset_trade INTEGER,
  maker_fill INTEGER, paper INTEGER DEFAULT 0
)
""",
    """
CREATE TABLE IF NOT EXISTS weight_updates (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  timestamp TEXT, trigger_reason TEXT,
  old_win_rate REAL, new_win_rate REAL,
  improvement REAL, changes TEXT
)
""",
    """
CREATE TABLE IF NOT EXISTS signal_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  timestamp TEXT, signal_name TEXT,
  old_weight REAL, new_weight REAL,
  accuracy_at_change REAL
)
""",
    """
CREATE TABLE IF NOT EXISTS thought_trains (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  timestamp TEXT,
  trigger_reason TEXT,
  loss_pattern TEXT,
  root_cause TEXT,
  regime_at_time TEXT,
  changes_made TEXT,
  success INTEGER,
  win_rate_before REAL,
  win_rate_after_5_trades REAL
)
""",
    """
CREATE TABLE IF NOT EXISTS regime_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  timestamp TEXT,
  regime TEXT,
  trend_score REAL,
  volatility_ratio REAL,
  correlation_score REAL,
  duration_seconds INTEGER,
  pnl_during_regime REAL,
  best_strategy TEXT
)
""",
]


class TradeLogger:
    """Persists trades and optimization metadata asynchronously."""

    def __init__(self, db_path: str | Path = "data/trades.db") -> None:
        self.db_path = str(db_path)

    async def init(self) -> None:
        """Create schema if needed."""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.db_path) as db:
            for stmt in SCHEMA:
                await db.execute(stmt)
            await db.commit()

    async def log_trade(self, trade: dict[str, Any]) -> None:
        """Insert completed trade row."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO trades (
                  timestamp, asset, market_id, strategy, direction, entry_price, exit_price,
                  exit_reason, bet_size, shares, gross_pnl, net_pnl, pnl_pct, won,
                  held_past_33, extra_gain, exhaustion_score, confidence, edge_pct,
                  signals_fired, signal_scores, seconds_remaining_at_entry,
                  bankroll_at_entry, win_rate_10_at_entry, consecutive_losses_at_entry,
                  regime_at_entry, degradation_level_at_entry, oracle_lag_present,
                  cross_asset_trade, maker_fill, paper
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trade.get("timestamp", ""),
                    trade.get("asset", ""),
                    trade.get("market_id", ""),
                    trade.get("strategy", ""),
                    trade.get("direction", ""),
                    trade.get("entry_price", 0.0),
                    trade.get("exit_price", 0.0),
                    trade.get("exit_reason", ""),
                    trade.get("bet_size", 0.0),
                    trade.get("shares", 0.0),
                    trade.get("gross_pnl", 0.0),
                    trade.get("net_pnl", 0.0),
                    trade.get("pnl_pct", 0.0),
                    trade.get("won", 0),
                    trade.get("held_past_33", 0),
                    trade.get("extra_gain", 0.0),
                    trade.get("exhaustion_score", 0.0),
                    trade.get("confidence", 0.0),
                    trade.get("edge_pct", 0.0),
                    json.dumps(trade.get("signals_fired", [])),
                    json.dumps(trade.get("signal_scores", {})),
                    trade.get("seconds_remaining_at_entry", 0),
                    trade.get("bankroll_at_entry", 0.0),
                    trade.get("win_rate_10_at_entry", 0.0),
                    trade.get("consecutive_losses_at_entry", 0),
                    trade.get("regime_at_entry", "RANGING"),
                    trade.get("degradation_level_at_entry", trade.get("degradation_level", 0)),
                    int(bool(trade.get("oracle_lag_present", False))),
                    int(bool(trade.get("cross_asset_trade", False))),
                    int(bool(trade.get("maker", False))),
                    trade.get("paper", 0),
                ),
            )
            await db.commit()

    async def fetch_recent_trades(self, limit: int = 100) -> list[dict[str, Any]]:
        """Fetch recent trade rows as dictionaries."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT * FROM trades ORDER BY id DESC LIMIT ?", (limit,))
            rows = await cur.fetchall()
            return [dict(row) for row in rows]

    async def log_weight_update(self, row: dict[str, Any]) -> None:
        """Insert weight update event."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO weight_updates (timestamp, trigger_reason, old_win_rate, new_win_rate, improvement, changes) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    row.get("timestamp", ""),
                    row.get("trigger_reason", ""),
                    row.get("old_win_rate", 0.0),
                    row.get("new_win_rate", 0.0),
                    row.get("improvement", 0.0),
                    json.dumps(row.get("changes", {})),
                ),
            )
            await db.commit()

    async def log_thought_train(self, row: dict[str, Any]) -> None:
        """Persist thought-train diagnostics."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO thought_trains (
                  timestamp, trigger_reason, loss_pattern, root_cause, regime_at_time,
                  changes_made, success, win_rate_before, win_rate_after_5_trades
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row.get("timestamp", ""),
                    row.get("trigger_reason", ""),
                    row.get("loss_pattern", ""),
                    row.get("root_cause", ""),
                    row.get("regime_at_time", ""),
                    json.dumps(row.get("changes_made", {})),
                    int(bool(row.get("success", False))),
                    row.get("win_rate_before", 0.0),
                    row.get("win_rate_after_5_trades", 0.0),
                ),
            )
            await db.commit()
