"""Order book helpers."""

from __future__ import annotations


def imbalance(bid_depth: float, ask_depth: float) -> float:
    total = bid_depth + ask_depth
    if total <= 0:
        return 0.0
    return (bid_depth - ask_depth) / total


def whale_detected(largest_order: float, depth_total: float) -> bool:
    return depth_total > 0 and largest_order > depth_total * 0.35
