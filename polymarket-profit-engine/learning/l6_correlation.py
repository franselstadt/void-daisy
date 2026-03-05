"""L6 exponential decay correlation tracker."""

from __future__ import annotations

import asyncio
import json
import math
from pathlib import Path

from core.config import config
from core.event_bus import bus
from core.state import state


class L6Correlation:
    def __init__(self, path: str = 'data/correlation_state.json') -> None:
        self.path = Path(path)
        self._load()

    def _load(self) -> None:
        try:
            data = json.loads(self.path.read_text()) if self.path.exists() else {}
        except Exception:
            data = {}
        self.lags = data.get('lag', {'ETH': 8.0, 'SOL': 12.0, 'XRP': 15.0})
        self.strengths = data.get('strength', {'ETH': 0.8, 'SOL': 0.75, 'XRP': 0.6})

    def _save(self) -> None:
        self.path.write_text(json.dumps(
            {'lag': self.lags, 'strength': self.strengths}, indent=2, sort_keys=True))

    async def on_trade_exit(self, event: dict) -> None:
        if str(event.get('plan')) != 'PLAN_03':
            return
        asset = str(event.get('asset', ''))
        if asset not in self.lags:
            return
        won = int(event.get('won', 0)) == 1
        if won:
            observed_lag = float(event.get('hold_seconds', 0.0))
            if 0 < observed_lag < 60:
                self.lags[asset] = 0.8 * self.lags[asset] + 0.2 * observed_lag
        else:
            self.lags[asset] = 0.9 * self.lags[asset]

    async def run(self) -> None:
        bus.subscribe('TRADE_EXITED', self.on_trade_exit)
        halflife_hours = float(config.get('learning', 'l6_halflife_hours', default=4))
        halflife = halflife_hours * 3600
        interval = 60
        while True:
            try:
                dt = interval
                decay = 1 - math.exp(-dt / halflife)
                for asset in ['ETH', 'SOL', 'XRP']:
                    observed_corr = float(state.get(f'regime.avg_correlation', 0.7))
                    old_strength = self.strengths.get(asset, 0.7)
                    self.strengths[asset] = (1 - decay) * old_strength + decay * observed_corr

                    observed_lag = float(state.get(f'correlation.lag.{asset}', self.lags.get(asset, 10.0)))
                    old_lag = self.lags.get(asset, 10.0)
                    self.lags[asset] = (1 - decay) * old_lag + decay * observed_lag

                    state.set_sync(f'correlation.lag.{asset}', self.lags[asset])
                    state.set_sync(f'correlation.strength.{asset}', self.strengths[asset])
                    state.set_sync(f'learning.l6.correlation.{asset}.lag', self.lags[asset])
                    state.set_sync(f'learning.l6.correlation.{asset}.strength', self.strengths[asset])

                self._save()
            except Exception:
                pass
            await asyncio.sleep(interval)
