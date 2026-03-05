"""Hot deployment utilities for runtime parameter updates."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


class HotUpdater:
    """Writes config/weight updates with version archival."""

    def __init__(self, versions_dir: str | Path = "data/versions") -> None:
        self.versions_dir = Path(versions_dir)
        self.versions_dir.mkdir(parents=True, exist_ok=True)

    def _archive(self, path: Path) -> str:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        if path.exists():
            backup = self.versions_dir / f"{path.stem}_{ts}.json"
            backup.write_text(path.read_text())
        return ts

    def deploy_weights(self, weights: dict[str, float], path: str | Path = "data/signal_weights.json") -> str:
        """Archive and write new signal weights."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        ts = self._archive(target)
        target.write_text(json.dumps(weights, indent=2, sort_keys=True))
        return ts

    def deploy_beliefs(self, beliefs: dict[str, dict[str, float]], path: str | Path = "data/bayesian_beliefs.json") -> None:
        """Persist belief state for restart continuity."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(beliefs, indent=2, sort_keys=True))
