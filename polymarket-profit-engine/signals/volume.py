"""Volume analysis helpers."""

from __future__ import annotations


def spike(ratio_10_60: float) -> bool:
    return ratio_10_60 > 3.0


def climax(ratio_10_60: float, buy_pct: float) -> bool:
    return ratio_10_60 > 2.5 and (buy_pct > 0.8 or buy_pct < 0.2)


def exhaustion(ratio_10_60: float) -> bool:
    return ratio_10_60 < 0.6
