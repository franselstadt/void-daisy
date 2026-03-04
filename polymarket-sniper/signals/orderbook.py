"""Orderbook imbalance calculations."""

from __future__ import annotations

from typing import Any


def imbalance_score(orderbook: dict[str, Any], direction: str) -> float:
    """Compute normalized directional orderbook imbalance in [0, 1]."""
    bids = float(orderbook.get("bids_volume", orderbook.get("bids", 0.0)) or 0.0)
    asks = float(orderbook.get("asks_volume", orderbook.get("asks", 0.0)) or 0.0)
    total = bids + asks
    if total <= 0:
        return 0.5
    raw = bids / total
    if direction == "DOWN":
        raw = 1.0 - raw
    return max(0.0, min(1.0, raw))
