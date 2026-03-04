"""Lightweight acceptance backtester for updated parameters."""

from __future__ import annotations

import json
from typing import Any


def evaluate_weights(trades: list[dict[str, Any]], weights: dict[str, float], threshold: float = 3.5) -> float:
    """Estimate candidate win rate from recent trade history."""
    if not trades:
        return 0.5
    selected: list[dict[str, Any]] = []
    for trade in trades:
        raw = trade.get("signal_scores", "{}")
        try:
            scores = raw if isinstance(raw, dict) else json.loads(raw)
        except Exception:  # noqa: BLE001
            scores = {}
        score_sum = sum(float(weights.get(k, 0.0)) for k in scores)
        if score_sum >= threshold:
            selected.append(trade)
    sample = selected if selected else trades
    wins = sum(1 for row in sample if int(row.get("won", 0)) == 1)
    return wins / max(1, len(sample))
