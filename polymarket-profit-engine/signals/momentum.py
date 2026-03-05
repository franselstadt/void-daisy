"""Momentum helpers."""

from __future__ import annotations


def direction_from_velocity(v: float) -> str:
    if v > 0:
        return 'UP'
    if v < 0:
        return 'DOWN'
    return 'FLAT'


def acceleration_confirming(v30: float, accel: float) -> bool:
    return (v30 > 0 and accel > 0) or (v30 < 0 and accel < 0)
