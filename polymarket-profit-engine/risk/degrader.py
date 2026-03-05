"""Graceful degradation controller."""

from __future__ import annotations

from core.state import state

LEVELS = {
    0: {'name': 'NORMAL', 'size_mult': 1.0, 'conf_bonus': 0.0, 'exhaustion_bonus': 0.0, 'plans': 'ALL'},
    1: {'name': 'REDUCED', 'size_mult': 0.70, 'conf_bonus': 0.03, 'exhaustion_bonus': 0.3, 'plans': 'ALL'},
    2: {'name': 'DEFENSIVE', 'size_mult': 0.45, 'conf_bonus': 0.06, 'exhaustion_bonus': 0.7, 'plans': ['PLAN_02','PLAN_01','PLAN_10']},
    3: {'name': 'SURVIVAL', 'size_mult': 0.25, 'conf_bonus': 0.10, 'exhaustion_bonus': 1.0, 'plans': ['PLAN_02']},
}


def assess() -> int:
    losses = int(state.get('stats.consecutive_losses', 0))
    dd = float(state.get('stats.drawdown_pct', 0.0))
    level = 0
    if losses >= 3 or dd >= 0.10: level = 1
    if losses >= 5 or dd >= 0.15: level = 2
    if losses >= 7 or dd >= 0.18: level = 3
    if float(state.get('stats.win_rate_10', 0.5)) >= 0.65 and losses == 0 and level > 0:
        level -= 1
    state.set_sync('bot.degradation_level', level)
    state.set_sync('degradation_level', level)
    return level
