"""Lightweight in-sample acceptance backtest."""

from __future__ import annotations

import json
from typing import Any


def _score_trade(trade: dict[str, Any], weights: dict[str, float]) -> float:
    raw = trade.get("signal_scores", "{}")
    try:
        scores = raw if isinstance(raw, dict) else json.loads(raw)
    except Exception:  # noqa: BLE001
        scores = {}
    return sum(float(weights.get(k, 0.0)) for k in scores)


def evaluate_win_rate(trades: list[dict[str, Any]], weights: dict[str, float]) -> float:
    """Estimate win rate for thresholded selections under candidate weights."""
    selected = [t for t in trades if _score_trade(t, weights) >= 3.5]
    base = selected if selected else trades
    if not base:
        return 0.5
    wins = sum(1 for t in base if int(t.get("won", 0)) == 1)
    return wins / len(base)
