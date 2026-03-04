"""Volume signal helpers."""

from __future__ import annotations


def is_spike(volume_ratio_10_60: float, threshold: float = 3.0) -> bool:
    """Return whether short-term volume is materially elevated."""
    return volume_ratio_10_60 > threshold


def normalising(volume_ratio_10_60: float) -> bool:
    """Return whether volume has normalised after impulse move."""
    return volume_ratio_10_60 < 1.2
