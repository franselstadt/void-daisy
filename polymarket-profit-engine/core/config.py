"""Hot reloadable JSON config for runtime tuning."""

from __future__ import annotations

import json
from pathlib import Path
from threading import RLock
from typing import Any

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from core.logger import logger

DEFAULT = {
    "trading": {
        "min_bet": 1.0,
        "max_positions": 4,
        "max_total_exposure_pct": 0.40,
        "min_seconds": 100,
        "max_seconds": 270,
        "max_spread": 0.05,
        "min_confidence": 0.62,
        "min_exhaustion": 3.5,
        "maker_timeout_seconds": 3,
        "max_proxy_retries": 10
    },
    "window": {
        "prime_zone_start": 120,
        "prime_zone_end": 190
    },
    "assets": {
        "BTC": {"sniper": [0.06, 0.13], "momentum": [0.38, 0.62], "reversion_lo": [0.18, 0.34], "reversion_hi": [0.66, 0.82]},
        "ETH": {"sniper": [0.06, 0.13], "momentum": [0.36, 0.64], "reversion_lo": [0.17, 0.33], "reversion_hi": [0.67, 0.83]},
        "SOL": {"sniper": [0.05, 0.14], "momentum": [0.35, 0.65], "reversion_lo": [0.17, 0.33], "reversion_hi": [0.67, 0.83]},
        "XRP": {"sniper": [0.07, 0.13], "momentum": [0.38, 0.62], "reversion_lo": [0.18, 0.34], "reversion_hi": [0.66, 0.82]}
    }
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
                self._cfg = json.loads(self.path.read_text())
            except Exception:
                self._cfg = DEFAULT

    def start(self) -> None:
        if self._obs:
            return
        self._obs = Observer()
        self._obs.schedule(_Watcher(self), str(self.path.parent), recursive=False)
        self._obs.start()
        logger.info('config_watch_started', path=str(self.path))

    def get(self, key: str, default: Any = None) -> Any:
        parts = key.split('.')
        d: Any = self._cfg
        for p in parts:
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
            self.save()

    def save(self) -> None:
        with self._lock:
            self.path.write_text(json.dumps(self._cfg, indent=2, sort_keys=True))


config = Config()
