"""Hot reloadable JSON config for runtime tuning."""

from __future__ import annotations

from pathlib import Path
from threading import RLock
from typing import Any

import ujson
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from loguru import logger

DEFAULT: dict[str, Any] = {
    "version": 1,
    "trading": {
        "min_bet": 1.0,
        "max_bankroll_pct": 0.15,
        "max_positions": 4,
        "max_exposure_pct": 0.40,
        "max_total_exposure_pct": 0.40,
        "min_seconds": 100,
        "max_seconds": 270,
        "max_spread": 0.05,
        "min_confidence": 0.62,
        "min_exhaustion": 3.5,
        "maker_timeout_seconds": 3,
        "max_proxy_retries": 10,
    },
    "window": {
        "min_seconds_remaining": 45,
        "max_data_age_seconds": 3.0,
        "min_window_elapsed": 30,
        "prime_zone_start": 120,
        "prime_zone_end": 190,
    },
    "plans": {
        "PLAN_01": {"enabled": True, "min_exhaustion": 3.5, "min_confidence": 0.62, "entry_min": 0.05, "entry_max": 0.13, "min_seconds": 100, "max_seconds": 215},
        "PLAN_02": {"enabled": True, "min_oracle_lag": 2.5, "min_delta_pct": 0.003, "max_hold_seconds": 20},
        "PLAN_03": {"enabled": True, "min_lag_score": 0.05, "min_seconds": 80, "max_seconds": 270},
        "PLAN_04": {"enabled": True, "min_confidence": 0.68, "entry_min": 0.38, "entry_max": 0.62, "min_seconds": 150, "max_seconds": 270},
        "PLAN_05": {"enabled": True, "min_confidence": 0.60, "entry_lo_min": 0.17, "entry_lo_max": 0.32, "entry_hi_min": 0.68, "entry_hi_max": 0.83, "min_seconds": 150},
        "PLAN_06": {"enabled": True, "min_order_usdc": 500, "min_seconds": 90},
        "PLAN_07": {"enabled": True, "min_volume_ratio": 4.0, "min_seconds": 100},
        "PLAN_08": {"enabled": True, "min_seconds": 120, "news_detection_threshold": 3.0},
        "PLAN_09": {"enabled": True, "max_elapsed": 65, "min_velocity": 0.002},
        "PLAN_10": {"enabled": True, "min_assets_crashing": 3, "min_seconds": 90},
        "PLAN_11": {"enabled": True, "min_spread_ratio": 2.0, "min_seconds": 80},
        "PLAN_12": {"enabled": True, "prime_start": 120, "prime_end": 190, "relax_floor_confidence": 0.55, "relax_floor_exhaustion": 2.5},
    },
    "risk": {
        "drawdown_reduce_at": 0.10,
        "drawdown_critical_at": 0.15,
        "drawdown_stop_at": 0.20,
        "bankroll_hard_stop": 10.0,
        "consecutive_losses_reduce": 3,
        "consecutive_losses_critical": 5,
        "consecutive_losses_survival": 7,
    },
    "learning": {
        "min_trades_update": 15,
        "update_interval_secs": 300,
        "l1_prior_alpha": 2.0,
        "l1_prior_beta": 2.0,
        "l1_recency_10min": 4.0,
        "l1_recency_30min": 2.5,
        "l1_recency_60min": 1.5,
        "l2_process_noise": 0.001,
        "l2_measurement_noise": 0.1,
        "l4_ucb_c": 1.41,
        "l5_learning_rate": 0.01,
        "l5_max_weight_change": 0.20,
        "l6_halflife_hours": 4,
        "l7_discount": 0.95,
        "l8_optimize_every_secs": 3600,
    },
    "assets": {
        "BTC": {"sniper": [0.06, 0.13], "momentum": [0.38, 0.62], "reversion_lo": [0.18, 0.34], "reversion_hi": [0.66, 0.82]},
        "ETH": {"sniper": [0.06, 0.13], "momentum": [0.36, 0.64], "reversion_lo": [0.17, 0.33], "reversion_hi": [0.67, 0.83]},
        "SOL": {"sniper": [0.05, 0.14], "momentum": [0.35, 0.65], "reversion_lo": [0.17, 0.33], "reversion_hi": [0.67, 0.83]},
        "XRP": {"sniper": [0.07, 0.13], "momentum": [0.38, 0.62], "reversion_lo": [0.18, 0.34], "reversion_hi": [0.66, 0.82]},
    },
}


class _Watcher(FileSystemEventHandler):
    def __init__(self, cfg: 'Config') -> None:
        self.cfg = cfg

    def on_modified(self, event) -> None:  # type: ignore[no-untyped-def]
        if "config.json" in str(event.src_path):
            self.cfg._load()
            logger.info("Config hot-reloaded — no restart needed")


class Config:
    def __init__(self) -> None:
        self._path = Path("data/config.json")
        self._lock = RLock()
        self._data: dict[str, Any] = dict(DEFAULT)
        self._load()
        self._observer: Observer | None = None

    def _load(self) -> None:
        if self._path.exists():
            try:
                with open(self._path) as f:
                    with self._lock:
                        self._data = ujson.load(f)
                logger.info(f"Config loaded v{self._data.get('version', 1)}")
            except Exception as e:
                logger.error(f"Config load error: {e}")

    def _save(self) -> None:
        self._path.parent.mkdir(exist_ok=True)
        with open(self._path, "w") as f:
            ujson.dump(self._data, f, indent=2)

    def start(self) -> None:
        if self._observer:
            return
        self._observer = Observer()
        self._observer.schedule(_Watcher(self), str(self._path.parent), recursive=False)
        self._observer.daemon = True
        self._observer.start()

    def get(self, *keys: str, default: Any = None) -> Any:
        with self._lock:
            d = self._data
            for k in keys:
                if not isinstance(d, dict):
                    return default
                d = d.get(k, default)
            return d

    def update(self, updates: dict) -> None:
        def _deep(base: dict, upd: dict) -> None:
            for k, v in upd.items():
                if isinstance(v, dict) and isinstance(base.get(k), dict):
                    _deep(base[k], v)
                else:
                    base[k] = v
        with self._lock:
            _deep(self._data, updates)
            self._data["version"] = self._data.get("version", 1) + 1
        self._save()
        logger.info(f"Config updated → v{self._data['version']}")


config = Config()
