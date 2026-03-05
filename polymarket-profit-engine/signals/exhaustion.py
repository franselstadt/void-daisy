"""Weighted exhaustion scoring with hot-reload weights."""

from __future__ import annotations

import json
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

WEIGHTS_DEFAULT = {
    'velocity_slowing': 1.4,
    'acceleration_positive': 1.6,
    'spread_tightening': 0.9,
    'volume_exhaustion': 0.8,
    'price_stabilising': 1.1,
    'bid_depth_building': 1.3,
    'rsi_extreme': 1.8,
    'round_number_proximity': 0.5,
    'btc_led_and_stabilising': 1.2,
    'chainlink_lag': 1.4,
    'cross_asset_divergence': 1.0,
    'consecutive_down_candles': 0.7,
    'vwap_extreme': 0.9,
}


class _Handler(FileSystemEventHandler):
    def __init__(self, engine: 'ExhaustionEngine') -> None:
        self.engine = engine

    def on_modified(self, event):  # type: ignore[no-untyped-def]
        if Path(event.src_path) == self.engine.path:
            self.engine.reload()


class ExhaustionEngine:
    def __init__(self, path: str = 'data/signal_weights.json') -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.weights = dict(WEIGHTS_DEFAULT)
        if not self.path.exists():
            self.path.write_text(json.dumps(self.weights, indent=2, sort_keys=True))
        self.reload()
        self.obs: Observer | None = None

    def start(self) -> None:
        if self.obs:
            return
        self.obs = Observer()
        self.obs.schedule(_Handler(self), str(self.path.parent), recursive=False)
        self.obs.start()

    def reload(self) -> None:
        try:
            self.weights = json.loads(self.path.read_text())
        except Exception:
            self.weights = dict(WEIGHTS_DEFAULT)

    def score(self, ctx: dict) -> dict:
        score = 0.0
        fired: list[str] = []
        v10 = abs(float(ctx.get('v10', 0.0)))
        v30 = abs(float(ctx.get('v30', 0.0)))
        if v30 > 0 and v10 < v30 * 0.6:
            score += self.weights.get('velocity_slowing', 0)
            fired.append('velocity_slowing')
        if float(ctx.get('accel', 0.0)) > 0 and ctx.get('direction') == 'UP':
            score += self.weights.get('acceleration_positive', 0)
            fired.append('acceleration_positive')
        if float(ctx.get('spread', 0.0)) < float(ctx.get('prev_spread', 1.0)) * 0.8:
            score += self.weights.get('spread_tightening', 0)
            fired.append('spread_tightening')
        if float(ctx.get('vol_ratio', 1.0)) < 0.6:
            score += self.weights.get('volume_exhaustion', 0)
            fired.append('volume_exhaustion')
        if v30 > 0 and v10 < v30 * 0.3:
            score += self.weights.get('price_stabilising', 0)
            fired.append('price_stabilising')
        if float(ctx.get('bid_depth_delta', 0.0)) > 0:
            score += self.weights.get('bid_depth_building', 0)
            fired.append('bid_depth_building')
        rsi = float(ctx.get('rsi', 50.0))
        if (ctx.get('direction') == 'UP' and rsi < 22) or (ctx.get('direction') == 'DOWN' and rsi > 78):
            score += self.weights.get('rsi_extreme', 0)
            fired.append('rsi_extreme')
        if bool(ctx.get('round_prox', False)):
            score += self.weights.get('round_number_proximity', 0)
            fired.append('round_number_proximity')
        if bool(ctx.get('btc_led', False)):
            score += self.weights.get('btc_led_and_stabilising', 0)
            fired.append('btc_led_and_stabilising')
        if float(ctx.get('oracle_lag', 0.0)) > 2.0:
            score += self.weights.get('chainlink_lag', 0)
            fired.append('chainlink_lag')
        if float(ctx.get('xasset_div', 0.0)) > 0.15:
            score += self.weights.get('cross_asset_divergence', 0)
            fired.append('cross_asset_divergence')
        if int(ctx.get('candles', 0)) >= 3:
            score += self.weights.get('consecutive_down_candles', 0)
            fired.append('consecutive_down_candles')
        if (ctx.get('direction') == 'UP' and float(ctx.get('vwap_dev', 0.0)) < -0.004) or (ctx.get('direction') == 'DOWN' and float(ctx.get('vwap_dev', 0.0)) > 0.004):
            score += self.weights.get('vwap_extreme', 0)
            fired.append('vwap_extreme')
        return {'score': score, 'signals_fired': fired}


exhaustion_engine = ExhaustionEngine()
