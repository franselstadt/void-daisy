"""EV-based opportunity ranker."""

from __future__ import annotations

from typing import Any

from regime.fitness import STRATEGY_FITNESS

STRATEGY_AVG_WIN = {
    "ORACLE_ARB": 0.35,
    "CROSS_ASSET_LAG": 0.30,
    "EXHAUSTION_SNIPER": 0.38,
    "MOMENTUM_RIDER": 0.55,
    "MEAN_REVERSION": 0.28,
}

URGENCY = {
    "ORACLE_ARB": 3.0,
    "CROSS_ASSET_LAG": 2.5,
    "MOMENTUM_RIDER": 1.5,
    "EXHAUSTION_SNIPER": 1.2,
    "MEAN_REVERSION": 1.0,
}


class OpportunityRanker:
    """Ranks opportunities competing for position slots."""

    def rank(self, opportunities: list[dict[str, Any]], snapshot: dict[str, Any]) -> list[dict[str, Any]]:
        """Return opportunities sorted by highest final score."""
        regime = str(snapshot.get("bot", {}).get("current_regime", "RANGING"))
        scored: list[dict[str, Any]] = []
        by_strategy_wr = snapshot.get("stats", {}).get("win_rate_20", {})
        for opp in opportunities:
            strategy = str(opp.get("strategy", "EXHAUSTION_SNIPER"))
            win_prob = float(opp.get("confidence", 0.5))
            entry_price = float(opp.get("entry_price", 0.5))
            avg_win_pct = STRATEGY_AVG_WIN.get(strategy, 0.3)
            avg_loss_pct = entry_price
            ev = (win_prob * avg_win_pct) - ((1 - win_prob) * avg_loss_pct)
            ev *= STRATEGY_FITNESS.get(strategy, {}).get(regime, 0.5)
            wr = float(by_strategy_wr.get(strategy, 0.5))
            ev *= 0.6 + (wr * 0.8)
            if strategy == "ORACLE_ARB":
                ev *= 1.5
            final_score = ev * URGENCY.get(strategy, 1.0)
            scored.append({**opp, "rank_score": final_score})
        return sorted(scored, key=lambda x: x["rank_score"], reverse=True)
