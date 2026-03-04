"""Weighted exhaustion score engine with hot-reloaded JSON weights."""

from __future__ import annotations

import json
from pathlib import Path
from threading import RLock
from typing import Any

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from core.logger import logger

DEFAULT_WEIGHTS = {
    "velocity_slowing": 1.4,
    "acceleration_positive": 1.6,
    "spread_tightening": 0.9,
    "volume_exhaustion": 0.8,
    "price_stabilising": 1.1,
    "bid_depth_building": 1.3,
    "rsi_extreme": 1.8,
    "round_number_proximity": 0.5,
    "btc_led_and_stabilising": 1.2,
    "chainlink_lag": 1.2,
    "consecutive_down_candles": 0.7,
    "cross_asset_divergence": 1.0,
    "vwap_extreme": 0.9,
    # compatibility aliases
    "volume_dropping": 0.6,
    "bids_building": 1.3,
    "rsi_oversold": 1.8,
    "btc_led_move": 1.2,
    "consecutive_candles": 0.7,
}


class _WeightHandler(FileSystemEventHandler):
    def __init__(self, scorer: "ExhaustionScorer") -> None:
        self.scorer = scorer

    def on_modified(self, event: FileSystemEvent) -> None:
        if Path(event.src_path) == self.scorer.path:
            self.scorer.reload()


class ExhaustionScorer:
    """Computes weighted exhaustion score and fired signals."""

    def __init__(self, path: str | Path = "data/signal_weights.json") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._weights = dict(DEFAULT_WEIGHTS)
        self._observer: Observer | None = None
        if not self.path.exists():
            self.path.write_text(json.dumps(self._weights, indent=2, sort_keys=True))
        self.reload()

    def start_watching(self) -> None:
        """Enable hot-reload on weight file updates."""
        if self._observer:
            return
        handler = _WeightHandler(self)
        self._observer = Observer()
        self._observer.schedule(handler, str(self.path.parent), recursive=False)
        self._observer.start()

    def reload(self) -> None:
        """Reload weights from disk."""
        with self._lock:
            try:
                self._weights = json.loads(self.path.read_text())
                logger.info("weights_reloaded", path=str(self.path))
            except Exception as exc:  # noqa: BLE001
                logger.warning("weights_reload_failed", error=str(exc))
                self._weights = dict(DEFAULT_WEIGHTS)

    @property
    def weights(self) -> dict[str, float]:
        with self._lock:
            return dict(self._weights)

    def score(self, context: dict[str, Any]) -> dict[str, Any]:
        """Return exhaustion score and signal contribution map."""
        with self._lock:
            w = self._weights

        direction = context.get("direction", "UP")
        v10 = abs(float(context.get("velocity_10s", 0.0)))
        v30 = abs(float(context.get("velocity_30s", 0.0)))
        spread = float(context.get("spread", 0.0))
        prev_spread = float(context.get("prev_spread", spread))
        volume_ratio = float(context.get("volume_ratio", 1.0))
        rsi = float(context.get("rsi_14", 50.0))
        spot = float(context.get("spot_price", 0.0))
        accel = float(context.get("acceleration", 0.0))
        vwap_dev = float(context.get("vwap_deviation", 0.0))
        orderbook = context.get("orderbook", {})
        btc_v = float(context.get("btc_velocity_10s", 0.0))
        btc_accel = float(context.get("btc_acceleration", 0.0))
        lag = float(context.get("oracle_lag_seconds", 0.0))
        candles = int(context.get("consecutive_candles", 0))
        div = abs(float(context.get("cross_asset_divergence", 0.0)))

        fired: list[str] = []
        scores: dict[str, float] = {}

        def trigger(name: str, cond: bool) -> None:
            if cond:
                fired.append(name)
                scores[name] = float(w.get(name, 0.0))

        trigger("velocity_slowing", v30 > 0 and v10 < v30 * 0.6)
        trigger("acceleration_positive", accel > 0 and direction == "UP")
        trigger("spread_tightening", prev_spread > 0 and spread < prev_spread * 0.8)
        trigger("volume_exhaustion", volume_ratio < 0.6)
        trigger("volume_dropping", volume_ratio < 0.6)
        trigger("price_stabilising", v30 > 0 and v10 < v30 * 0.3)
        bids = float(orderbook.get("bids_volume", 0.0))
        asks = float(orderbook.get("asks_volume", 0.0))
        trigger("bid_depth_building", bids > asks * 1.1)
        trigger("bids_building", bids > asks * 1.1)
        trigger("rsi_extreme", (direction == "UP" and rsi < 22) or (direction == "DOWN" and rsi > 78))
        trigger("rsi_oversold", (direction == "UP" and rsi < 25) or (direction == "DOWN" and rsi > 75))
        if spot > 0:
            round_unit = round(spot / 1000) * 1000
            trigger("round_number_proximity", abs(spot - round_unit) / spot <= 0.001)
        else:
            trigger("round_number_proximity", False)
        trigger(
            "btc_led_and_stabilising",
            (
                direction == "UP"
                and btc_v > 0
                and abs(btc_v) > abs(float(context.get("velocity_10s", 0.0)))
                and btc_accel > 0
            )
            or (
                direction == "DOWN"
                and btc_v < 0
                and abs(btc_v) > abs(float(context.get("velocity_10s", 0.0)))
                and btc_accel < 0
            ),
        )
        trigger("btc_led_move", (direction == "UP" and btc_v > 0) or (direction == "DOWN" and btc_v < 0))
        trigger("chainlink_lag", lag > 2.0)
        trigger("consecutive_down_candles", candles >= 3)
        trigger("consecutive_candles", candles >= 3)
        trigger("cross_asset_divergence", div > 0.15)
        trigger("vwap_extreme", (direction == "UP" and vwap_dev < -0.004) or (direction == "DOWN" and vwap_dev > 0.004))

        total = round(sum(scores.values()), 4)
        return {"score": total, "signals_fired": fired, "signal_scores": scores}
