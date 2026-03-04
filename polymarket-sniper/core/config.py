"""Hot-reloadable JSON configuration manager."""

from __future__ import annotations

import json
from pathlib import Path
from threading import RLock
from typing import Any

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from core.event_bus import bus
from core.logger import logger


DEFAULT_CONFIG: dict[str, Any] = {
    "assets": {
        "BTC": {
            "entry_sniper": [0.06, 0.13],
            "entry_momentum": [0.38, 0.62],
            "entry_reversion_low": [0.18, 0.34],
            "entry_reversion_high": [0.66, 0.82],
            "min_conf_sniper": 0.65,
            "min_conf_momentum": 0.68,
            "volatility_mult": 1.0,
            "is_anchor": True,
        },
        "ETH": {
            "entry_sniper": [0.06, 0.13],
            "entry_momentum": [0.36, 0.64],
            "entry_reversion_low": [0.17, 0.33],
            "entry_reversion_high": [0.67, 0.83],
            "min_conf_sniper": 0.62,
            "min_conf_momentum": 0.66,
            "volatility_mult": 1.1,
            "correlation_leader": "BTC",
            "initial_lag_seconds": 8,
        },
        "SOL": {
            "entry_sniper": [0.05, 0.14],
            "entry_momentum": [0.35, 0.65],
            "entry_reversion_low": [0.17, 0.33],
            "entry_reversion_high": [0.67, 0.83],
            "min_conf_sniper": 0.70,
            "min_conf_momentum": 0.72,
            "volatility_mult": 1.2,
            "correlation_leader": "BTC",
            "initial_lag_seconds": 12,
        },
        "XRP": {
            "entry_sniper": [0.07, 0.13],
            "entry_momentum": [0.38, 0.62],
            "entry_reversion_low": [0.18, 0.34],
            "entry_reversion_high": [0.66, 0.82],
            "min_conf_sniper": 0.68,
            "min_conf_momentum": 0.70,
            "volatility_mult": 0.85,
            "news_blackout_enabled": True,
        },
    },
    "trading": {
        "min_bet": 1.0,
        "max_bankroll_pct": 0.15,
        "max_total_exposure_pct": 0.40,
        "max_positions": 4,
        "max_positions_per_strategy": 2,
        "min_seconds": 100,
        "max_seconds": 270,
        "max_spread": 0.05,
        "min_exhaustion": 3.5,
        "min_edge_pct": 0.08,
        "profit_target": 0.33,
    },
    "sizing": {
        "kelly": 0.5,
        "confidence_multipliers": {"high": 1.4, "mid": 1.2, "base": 1.0, "low": 0.75},
        "performance_multipliers": {"great": 1.25, "good": 1.0, "neutral": 0.70, "bad": 0.45},
    },
    "risk": {
        "drawdown_reduced": 0.10,
        "drawdown_defensive": 0.15,
        "drawdown_survival": 0.18,
    },
    "regime": {
        "detector_interval": 60,
        "history_file": "data/regime_history.json",
    },
    "learning": {
        "min_trades": 15,
        "update_interval": 900,
        "backtest_window": 100,
    },
}


class _ConfigFileHandler(FileSystemEventHandler):
    """Watchdog handler that triggers config reload."""

    def __init__(self, config_manager: "ConfigManager") -> None:
        self.config_manager = config_manager

    def on_modified(self, event: FileSystemEvent) -> None:
        if Path(event.src_path) == self.config_manager.path:
            self.config_manager.reload()


class ConfigManager:
    """JSON config with RLock and hot-reload notifications."""

    def __init__(self, path: str | Path = "data/config.json") -> None:
        self.path = Path(path)
        self._lock = RLock()
        self._observer: Observer | None = None
        self._config: dict[str, Any] = {}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._config = DEFAULT_CONFIG
            self.save()
        self.reload()

    def start_watching(self) -> None:
        """Start watchdog observer for near-instant hot reload."""
        if self._observer:
            return
        handler = _ConfigFileHandler(self)
        self._observer = Observer()
        self._observer.schedule(handler, str(self.path.parent), recursive=False)
        self._observer.start()
        logger.info("config_watch_started", path=str(self.path))

    def stop_watching(self) -> None:
        """Stop watchdog observer."""
        if not self._observer:
            return
        self._observer.stop()
        self._observer.join(timeout=2)
        self._observer = None

    def reload(self) -> None:
        """Reload config from disk with fallback defaults."""
        with self._lock:
            try:
                self._config = json.loads(self.path.read_text())
                logger.info("config_reloaded", path=str(self.path))
            except Exception as exc:  # noqa: BLE001
                logger.error("config_reload_failed", error=str(exc))
                self._config = DEFAULT_CONFIG

    def get(self, *keys: str, default: Any = None) -> Any:
        """Read nested config key path."""
        with self._lock:
            current: Any = self._config
            for key in keys:
                if not isinstance(current, dict) or key not in current:
                    return default
                current = current[key]
            return current

    def update(self, patch: dict[str, Any]) -> None:
        """Merge patch at top level and persist to disk."""
        with self._lock:
            for key, value in patch.items():
                if isinstance(value, dict) and isinstance(self._config.get(key), dict):
                    self._config[key].update(value)
                else:
                    self._config[key] = value
            self.save()

    def save(self) -> None:
        """Persist current config to disk."""
        with self._lock:
            self.path.write_text(json.dumps(self._config, indent=2, sort_keys=True))

    async def notify_updated(self) -> None:
        """Emit config update event for subscribers."""
        await bus.publish("CONFIG_UPDATED", {"path": str(self.path)})


config = ConfigManager()
