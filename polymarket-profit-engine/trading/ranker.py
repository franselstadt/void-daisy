"""Expected value based opportunity ranker."""

from __future__ import annotations

from core.state import state

FITNESS = {
    'PLAN_01': {'TRENDING_UP': 0.6, 'TRENDING_DOWN': 0.9, 'RANGING': 1.0, 'VOLATILE': 0.8, 'QUIET': 0.5, 'NEWS_DRIVEN': 0.4, 'DECORRELATED': 0.9},
    'PLAN_02': {'TRENDING_UP': 1.0, 'TRENDING_DOWN': 1.0, 'RANGING': 0.7, 'VOLATILE': 1.0, 'QUIET': 0.4, 'NEWS_DRIVEN': 0.9, 'DECORRELATED': 0.8},
    'PLAN_03': {'TRENDING_UP': 0.7, 'TRENDING_DOWN': 0.7, 'RANGING': 0.8, 'VOLATILE': 0.8, 'QUIET': 0.7, 'NEWS_DRIVEN': 0.5, 'DECORRELATED': 0.8},
    'PLAN_04': {'TRENDING_UP': 1.0, 'TRENDING_DOWN': 1.0, 'RANGING': 0.2, 'VOLATILE': 0.5, 'QUIET': 0.3, 'NEWS_DRIVEN': 0.6, 'DECORRELATED': 0.5},
    'PLAN_05': {'TRENDING_UP': 0.2, 'TRENDING_DOWN': 0.2, 'RANGING': 1.0, 'VOLATILE': 0.4, 'QUIET': 0.8, 'NEWS_DRIVEN': 0.1, 'DECORRELATED': 0.7},
    'PLAN_06': {'TRENDING_UP': 0.8, 'TRENDING_DOWN': 0.8, 'RANGING': 0.8, 'VOLATILE': 0.8, 'QUIET': 0.5, 'NEWS_DRIVEN': 0.6, 'DECORRELATED': 0.8},
    'PLAN_07': {'TRENDING_UP': 0.9, 'TRENDING_DOWN': 0.9, 'RANGING': 0.6, 'VOLATILE': 1.0, 'QUIET': 0.4, 'NEWS_DRIVEN': 0.9, 'DECORRELATED': 0.8},
    'PLAN_08': {'TRENDING_UP': 0.4, 'TRENDING_DOWN': 0.4, 'RANGING': 0.3, 'VOLATILE': 0.5, 'QUIET': 0.2, 'NEWS_DRIVEN': 1.0, 'DECORRELATED': 0.6},
    'PLAN_09': {'TRENDING_UP': 0.7, 'TRENDING_DOWN': 0.7, 'RANGING': 0.6, 'VOLATILE': 0.6, 'QUIET': 0.5, 'NEWS_DRIVEN': 0.6, 'DECORRELATED': 0.5},
    'PLAN_10': {'TRENDING_UP': 1.0, 'TRENDING_DOWN': 1.0, 'RANGING': 0.6, 'VOLATILE': 0.9, 'QUIET': 0.3, 'NEWS_DRIVEN': 0.4, 'DECORRELATED': 0.1},
    'PLAN_11': {'TRENDING_UP': 0.6, 'TRENDING_DOWN': 0.6, 'RANGING': 0.7, 'VOLATILE': 0.7, 'QUIET': 0.6, 'NEWS_DRIVEN': 0.4, 'DECORRELATED': 0.7},
    'PLAN_12': {'TRENDING_UP': 0.8, 'TRENDING_DOWN': 0.8, 'RANGING': 0.9, 'VOLATILE': 0.7, 'QUIET': 0.7, 'NEWS_DRIVEN': 0.5, 'DECORRELATED': 0.7},
}

STRAT_AVG_WIN = {f'PLAN_{i:02d}': 0.3 for i in range(1, 13)}
STRAT_AVG_WIN.update({'PLAN_02': 0.35, 'PLAN_04': 0.55, 'PLAN_01': 0.38, 'PLAN_05': 0.28, 'PLAN_10': 0.34})
URGENCY = {'PLAN_02': 3.0, 'PLAN_10': 2.5, 'PLAN_04': 1.5, 'PLAN_01': 1.2, 'PLAN_05': 1.0}


def rank(opps: list[dict]) -> list[dict]:
    regime = state.get('bot.current_regime', 'RANGING')
    out: list[dict] = []
    for opp in opps:
        plan = str(opp.get('plan', 'PLAN_01'))
        p = float(opp.get('confidence', 0.5))
        entry = float(opp.get('entry_price', 0.5))
        ev = (p * STRAT_AVG_WIN.get(plan, 0.3)) - ((1 - p) * entry)
        ev *= FITNESS.get(plan, {}).get(regime, 0.5)
        wr20 = float(state.get(f'stats.win_rate_20.{plan}', 0.5))
        ev *= 0.6 + wr20 * 0.8
        if plan == 'PLAN_02':
            ev *= 1.5
        urgency = URGENCY.get(plan, 1.2)
        out.append({**opp, 'rank_score': ev * urgency})
    return sorted(out, key=lambda x: float(x.get('rank_score', 0.0)), reverse=True)
