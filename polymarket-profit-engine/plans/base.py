"""Base plan interfaces and opportunity model."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class Opportunity:
    asset: str
    plan: str
    strategy: str
    direction: str
    entry_price: float
    confidence: float
    exhaustion_score: float
    edge_pct: float
    ev: float
    market_id: str
    token_id: str
    seconds_remaining: int
    window_elapsed: int
    spread: float
    signals_fired: list[str]
    signal_scores: dict[str, float]
    urgency: float
    stop_loss_price: float
    timestamp: float

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out['event_type'] = 'SNIPE_OPPORTUNITY'
        return out


class BasePlan:
    name = 'BASE'

    def evaluate(self, ctx: dict[str, Any]) -> Opportunity | None:
        raise NotImplementedError

    def _mk(self, ctx: dict[str, Any], direction: str, entry_price: float, confidence: float, exhaustion: float, edge: float, ev: float, fired: list[str]) -> Opportunity:
        return Opportunity(
            asset=str(ctx['asset']),
            plan=self.name,
            strategy=self.name,
            direction=direction,
            entry_price=float(entry_price),
            confidence=float(confidence),
            exhaustion_score=float(exhaustion),
            edge_pct=float(edge),
            ev=float(ev),
            market_id=str(ctx.get('market_id', '')),
            token_id=str(ctx.get('token_id', '')),
            seconds_remaining=int(ctx.get('seconds_remaining', 0)),
            window_elapsed=int(ctx.get('window_elapsed', 0)),
            spread=float(ctx.get('spread', 0.0)),
            signals_fired=fired,
            signal_scores={},
            urgency=getattr(self, 'urgency', 1.0),
            stop_loss_price=0.02,
            timestamp=float(ctx.get('timestamp', time.time())),
        )
