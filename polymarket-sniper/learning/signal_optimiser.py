"""Signal weight optimisation by lift ratio."""

from __future__ import annotations

import json
from typing import Any


def _win_rate(trades: list[dict[str, Any]]) -> float:
    if not trades:
        return 0.5
    wins = sum(1 for t in trades if int(t.get("won", 0)) == 1)
    return wins / len(trades)


def optimise_weights(trades: list[dict[str, Any]], current_weights: dict[str, float]) -> tuple[dict[str, float], dict[str, float]]:
    """Adjust each weight by lift ratio with max 20% bounded update."""
    overall = max(0.05, _win_rate(trades))
    updated = dict(current_weights)
    lifts: dict[str, float] = {}

    for signal_name, old_w in current_weights.items():
        with_sig = []
        for trade in trades:
            raw = trade.get("signal_scores", "{}")
            try:
                scores = raw if isinstance(raw, dict) else json.loads(raw)
            except Exception:  # noqa: BLE001
                scores = {}
            if signal_name in scores:
                with_sig.append(trade)

        wr_signal = _win_rate(with_sig) if with_sig else overall
        lift = wr_signal / overall if overall > 0 else 1.0
        lifts[signal_name] = lift

        proposed = old_w * lift
        lower = old_w * 0.8
        upper = old_w * 1.2
        updated[signal_name] = max(lower, min(upper, proposed))

    return updated, lifts
