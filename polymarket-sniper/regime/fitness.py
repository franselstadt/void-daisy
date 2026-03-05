"""Strategy fitness matrix by detected market regime."""

from __future__ import annotations

from typing import Literal

Regime = Literal["TRENDING_UP", "TRENDING_DOWN", "RANGING", "VOLATILE", "QUIET", "NEWS_DRIVEN", "DECORRELATED"]

STRATEGY_FITNESS: dict[str, dict[Regime, float]] = {
    "EXHAUSTION_SNIPER": {
        "TRENDING_UP": 0.6,
        "TRENDING_DOWN": 0.9,
        "RANGING": 1.0,
        "VOLATILE": 0.8,
        "QUIET": 0.5,
        "NEWS_DRIVEN": 0.4,
        "DECORRELATED": 0.9,
    },
    "MOMENTUM_RIDER": {
        "TRENDING_UP": 1.0,
        "TRENDING_DOWN": 1.0,
        "RANGING": 0.2,
        "VOLATILE": 0.5,
        "QUIET": 0.3,
        "NEWS_DRIVEN": 0.6,
        "DECORRELATED": 0.5,
    },
    "ORACLE_ARB": {
        "TRENDING_UP": 1.0,
        "TRENDING_DOWN": 1.0,
        "RANGING": 0.7,
        "VOLATILE": 1.0,
        "QUIET": 0.4,
        "NEWS_DRIVEN": 0.9,
        "DECORRELATED": 0.8,
    },
    "MEAN_REVERSION": {
        "TRENDING_UP": 0.2,
        "TRENDING_DOWN": 0.2,
        "RANGING": 1.0,
        "VOLATILE": 0.4,
        "QUIET": 0.8,
        "NEWS_DRIVEN": 0.1,
        "DECORRELATED": 0.7,
    },
    "CROSS_ASSET_LAG": {
        "TRENDING_UP": 1.0,
        "TRENDING_DOWN": 1.0,
        "RANGING": 0.6,
        "VOLATILE": 0.9,
        "QUIET": 0.3,
        "NEWS_DRIVEN": 0.4,
        "DECORRELATED": 0.1,
    },
}


def get_active_engines(regime: Regime) -> list[str]:
    """Return engine names considered active in the given regime."""
    return [engine for engine, matrix in STRATEGY_FITNESS.items() if matrix[regime] >= 0.5]


def get_engine_weight(engine: str, regime: Regime) -> float:
    """Return fitness weight for engine in regime."""
    return STRATEGY_FITNESS.get(engine, {}).get(regime, 0.0)
