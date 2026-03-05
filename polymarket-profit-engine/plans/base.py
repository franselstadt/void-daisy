"""Base plan interfaces and opportunity model."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass
class Opportunity:
    plan: str
    asset: str
    direction: str
    market_id: str
    token_id: str
    entry_price: float
    confidence: float
    ev: float
    exhaustion_score: float
    signals_fired: list[str]
    signal_scores: dict[str, float]
    seconds_remaining: int
    window_elapsed: int
    urgency: float
    stop_loss_price: float
    timestamp: float
    strategy: str = ''
    edge_pct: float = 0.0
    spread: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out['event_type'] = 'SNIPE_OPPORTUNITY'
        return out


class BasePlan:
    name = 'BASE'
    plan_id: str = 'BASE'
    urgency: float = 1.0
    avg_win: float = 0.0
    regime_weights: dict[str, float] = {
        'TRENDING_UP': 1.0,
        'TRENDING_DOWN': 1.0,
        'RANGING': 1.0,
        'VOLATILE': 1.0,
        'QUIET': 1.0,
    }

    def check(self, ctx: dict[str, Any]) -> Opportunity | None:
        return self.evaluate(ctx)

    def evaluate(self, ctx: dict[str, Any]) -> Opportunity | None:
        raise NotImplementedError

    def ev(self, confidence: float, edge: float, entry_price: float) -> float:
        return confidence * edge - (1 - confidence) * entry_price

    def fitness(self, regime: str) -> float:
        return self.regime_weights.get(regime, 1.0) * max(0.01, self.avg_win)

    def load_weights(self, path: str = 'data/signal_weights.json') -> dict[str, float]:
        p = Path(path)
        if p.exists():
            try:
                return json.loads(p.read_text())
            except Exception:
                pass
        return {}

    def _mk(self, ctx: dict[str, Any], direction: str, entry_price: float, confidence: float, exhaustion: float, edge: float, ev: float, fired: list[str]) -> Opportunity:
        return Opportunity(
            plan=self.name,
            asset=str(ctx['asset']),
            direction=direction,
            market_id=str(ctx.get('market_id', '')),
            token_id=str(ctx.get('token_id', '')),
            entry_price=float(entry_price),
            confidence=float(confidence),
            ev=float(ev),
            exhaustion_score=float(exhaustion),
            signals_fired=fired,
            signal_scores={},
            seconds_remaining=int(ctx.get('seconds_remaining', 0)),
            window_elapsed=int(ctx.get('window_elapsed', 0)),
            urgency=self.urgency,
            stop_loss_price=0.02,
            timestamp=float(ctx.get('timestamp', time.time())),
            strategy=self.name,
            edge_pct=float(edge),
            spread=float(ctx.get('spread', 0.0)),
        )
