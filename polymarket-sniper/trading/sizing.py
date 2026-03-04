"""Position sizing using dynamic half-Kelly with hard caps."""

from __future__ import annotations


def calculate_bet_size(
    bankroll: float,
    entry_price: float,
    confidence: float,
    win_rate_10: float,
    consecutive_losses: int,
    asset: str,
) -> float:
    """Calculate bounded bet size with confidence/performance/degradation multipliers."""
    edge = confidence - (1 - confidence)
    odds = (1 / max(entry_price, 1e-6)) - 1
    kelly = (edge / odds) * 0.5 if odds > 0 else 0.0

    conf_mult = 1.4 if confidence >= 0.90 else 1.2 if confidence >= 0.82 else 1.0 if confidence >= 0.72 else 0.75
    perf_mult = 1.25 if win_rate_10 >= 0.75 else 1.0 if win_rate_10 >= 0.62 else 0.70 if win_rate_10 >= 0.48 else 0.45
    loss_mult = max(0.35, 1.0 - (consecutive_losses * 0.15))
    asset_mult = {"BTC": 1.0, "ETH": 1.1, "SOL": 1.2, "XRP": 0.85}.get(asset, 1.0)

    raw = bankroll * max(0.0, kelly) * conf_mult * perf_mult * loss_mult * asset_mult

    min_bet = 1.00
    max_bet = bankroll * 0.15
    return max(min_bet, min(max_bet, round(raw, 2)))
