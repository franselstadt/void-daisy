"""Dynamic Kelly sizing with degradation and exposure controls."""

from __future__ import annotations

from core.state import state


def calculate_bet_size(bankroll: float, entry_price: float, confidence: float, win_rate_10: float, consecutive_losses: int, asset: str, plan: str, degradation_level: int) -> float:
    edge = confidence - (1 - confidence)
    odds = (1 / max(entry_price, 1e-9)) - 1
    if odds <= 0:
        return 1.0
    kelly = max(0.0, (edge / odds) * 0.5)

    plan_mult = {
        'PLAN_02': 1.4, 'PLAN_10': 1.2, 'PLAN_01': 1.0, 'PLAN_04': 0.9, 'PLAN_05': 0.85,
    }.get(plan, 1.0)
    conf_mult = 1.4 if confidence >= 0.90 else 1.2 if confidence >= 0.82 else 1.0 if confidence >= 0.72 else 0.75
    perf_mult = 1.3 if win_rate_10 >= 0.75 else 1.0 if win_rate_10 >= 0.62 else 0.70 if win_rate_10 >= 0.48 else 0.45
    loss_mult = max(0.35, 1.0 - (consecutive_losses * 0.15))
    asset_mult = {'BTC': 1.0, 'ETH': 1.1, 'SOL': 1.2, 'XRP': 0.85}.get(asset, 1.0)
    deg_mult = {0: 1.0, 1: 0.70, 2: 0.45, 3: 0.25}.get(degradation_level, 1.0)
    rl_mult = float(state.get('learning.l7.rl_sizer.multiplier', 1.0))

    raw = bankroll * kelly * plan_mult * conf_mult * perf_mult * loss_mult * asset_mult * deg_mult * rl_mult

    min_bet = 1.0
    max_bet = bankroll * 0.15
    open_exp = float(state.get('stats.open_exposure', 0.0))
    available = (bankroll * 0.40) - open_exp
    max_bet = min(max_bet, max(0.0, available))
    return max(min_bet, min(max_bet, round(raw, 2)))
