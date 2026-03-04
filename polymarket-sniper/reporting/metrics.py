"""In-memory metrics aggregator."""

from __future__ import annotations

from collections import defaultdict
from typing import Any


class Metrics:
    """Tracks asset-level performance counters."""

    def __init__(self) -> None:
        self.asset = defaultdict(lambda: {"trades": 0, "wins": 0, "losses": 0, "pnl": 0.0, "best": 0.0})
        self.strategy = defaultdict(lambda: {"trades": 0, "wins": 0, "losses": 0, "pnl": 0.0})

    def on_exit(self, trade: dict[str, Any]) -> None:
        """Update counters from closed trade."""
        a = trade.get("asset", "UNK")
        row = self.asset[a]
        row["trades"] += 1
        pnl = float(trade.get("net_pnl", 0.0))
        row["pnl"] += pnl
        if pnl > 0:
            row["wins"] += 1
        else:
            row["losses"] += 1
        row["best"] = max(row["best"], float(trade.get("pnl_pct", 0.0)))
        s = trade.get("strategy", "UNKNOWN")
        srow = self.strategy[s]
        srow["trades"] += 1
        srow["wins"] += 1 if pnl > 0 else 0
        srow["losses"] += 0 if pnl > 0 else 1
        srow["pnl"] += pnl

    def summary(self) -> dict[str, dict[str, float]]:
        """Return current summary snapshot."""
        return {k: dict(v) for k, v in self.asset.items()}

    def strategy_summary(self) -> dict[str, dict[str, float]]:
        """Return strategy breakdown."""
        return {k: dict(v) for k, v in self.strategy.items()}
