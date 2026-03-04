"""Signal composer for strategy engines."""

from __future__ import annotations

from typing import Any

from signals.exhaustion import ExhaustionScorer
from signals.lag_detector import oracle_lag_present
from signals.momentum import alignment_score
from signals.orderbook import imbalance_score


class SignalComposer:
    """Combines signal families into strategy-ready confidence metrics."""

    def __init__(self, exhaustion: ExhaustionScorer) -> None:
        self.exhaustion = exhaustion

    def compose(self, strategy: str, context: dict[str, Any]) -> dict[str, Any]:
        """Build score and confidence for a strategy from shared context."""
        ex = self.exhaustion.score(context)
        momentum = alignment_score(
            str(context.get("direction", "UP")),
            float(context.get("velocity_10s", 0.0)),
            float(context.get("velocity_30s", 0.0)),
        )
        lag = oracle_lag_present(float(context.get("oracle_lag_seconds", 0.0)))
        book = imbalance_score(context.get("orderbook", {}), str(context.get("direction", "UP")))

        base = {
            "EXHAUSTION_SNIPER": [0.45, 0.20, 0.15, 0.20],
            "MOMENTUM_RIDER": [0.15, 0.45, 0.20, 0.20],
            "ORACLE_ARB": [0.10, 0.20, 0.55, 0.15],
            "MEAN_REVERSION": [0.35, 0.10, 0.20, 0.35],
            "CROSS_ASSET_LAG": [0.20, 0.20, 0.35, 0.25],
        }.get(strategy, [0.25, 0.25, 0.25, 0.25])

        confidence = max(0.0, min(0.99, (ex["score"] / 10.0) * base[0] + momentum * base[1] + lag * base[2] + book * base[3]))
        return {
            "confidence": confidence,
            "exhaustion_score": ex["score"],
            "signals_fired": ex["signals_fired"],
            "signal_scores": ex["signal_scores"],
        }
