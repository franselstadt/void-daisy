"""Oracle lag helpers."""

from __future__ import annotations


def oracle_lag_present(lag_seconds: float) -> float:
    """Map lag seconds to confidence contribution."""
    if lag_seconds <= 2.0:
        return 0.0
    if lag_seconds >= 8.0:
        return 1.0
    return (lag_seconds - 2.0) / 6.0
