"""Weight hot-deployment and version archival."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


class HotUpdater:
    """Writes active weight file and archives previous versions."""

    def __init__(self, weight_path: str | Path = "data/signal_weights.json", versions_dir: str | Path = "data/versions") -> None:
        self.weight_path = Path(weight_path)
        self.versions_dir = Path(versions_dir)
        self.weight_path.parent.mkdir(parents=True, exist_ok=True)
        self.versions_dir.mkdir(parents=True, exist_ok=True)

    def deploy(self, weights: dict[str, float]) -> str:
        """Archive old file and atomically write latest weights."""
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        if self.weight_path.exists():
            old = self.weight_path.read_text()
            (self.versions_dir / f"signal_weights_{ts}.json").write_text(old)
        self.weight_path.write_text(json.dumps(weights, indent=2, sort_keys=True))
        return ts
