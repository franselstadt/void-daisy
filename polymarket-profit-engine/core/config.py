"""Hot reloadable JSON config for runtime tuning."""

from __future__ import annotations

import ujson
from pathlib import Path
from threading import RLock
from typing import Any

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from core.logger import logger

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

    def on_modified(self, event):  # type: ignore[no-untyped-def]
        if Path(event.src_path) == self.cfg.path:
            self.cfg.reload()


class Config:
    def __init__(self, path: str = 'data/config.json') -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._cfg: dict[str, Any] = {}
        self._obs: Observer | None = None
        if not self.path.exists():
            self._cfg = DEFAULT
            self.save()
        self.reload()

    def reload(self) -> None:
        with self._lock:
            try:
                self._cfg = ujson.loads(self.path.read_text())
            except Exception:
                self._cfg = DEFAULT

    def start(self) -> None:
        if self._obs:
            return
        self._obs = Observer()
        self._obs.schedule(_Watcher(self), str(self.path.parent), recursive=False)
        self._obs.start()
        logger.info('config_watch_started', path=str(self.path))

    def get(self, *keys: str, default: Any = None) -> Any:
        d: Any = self._cfg
        for p in keys:
            if not isinstance(d, dict) or p not in d:
                return default
            d = d[p]
        return d

    def update(self, patch: dict[str, Any]) -> None:
        with self._lock:
            for k, v in patch.items():
                if isinstance(v, dict) and isinstance(self._cfg.get(k), dict):
                    self._cfg[k].update(v)
                else:
                    self._cfg[k] = v
            self._cfg["version"] = self._cfg.get("version", 0) + 1
            self.save()

    def save(self) -> None:
        with self._lock:
            self.path.write_text(ujson.dumps(self._cfg, indent=2, sort_keys=True))


config = Config()
