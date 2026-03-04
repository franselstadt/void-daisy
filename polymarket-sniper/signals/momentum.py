"""Momentum helpers."""

from __future__ import annotations


def alignment_score(direction: str, velocity_10s: float, velocity_30s: float) -> float:
    """Return 0..1 directional momentum alignment score."""
    sign_ok = (direction == "UP" and velocity_10s > 0) or (direction == "DOWN" and velocity_10s < 0)
    if not sign_ok:
        return 0.0
    accel_bonus = 0.2 if abs(velocity_10s) > abs(velocity_30s) else 0.0
    return min(1.0, 0.8 + accel_bonus)
