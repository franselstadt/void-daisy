"""Market regime detector running every 60 seconds."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from statistics import mean

import numpy as np

from core.event_bus import bus
from core.logger import logger
from core.state import AppState


class RegimeDetector:
    """Classifies market regime from rolling Binance metrics."""

    def __init__(self, state: AppState, history_path: str | Path = "data/regime_history.json") -> None:
        self.state = state
        self.history_path = Path(history_path)
        self.history_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.history_path.exists():
            self.history_path.write_text("[]")
        self._regime_since = time.time()

    def _corr(self, a: list[float], b: list[float]) -> float:
        if len(a) < 3 or len(b) < 3:
            return 0.0
        return float(np.corrcoef(np.array(a), np.array(b))[0, 1])

    async def _classify(self) -> dict[str, float | str]:
        snapshot = await self.state.snapshot()
        feed = snapshot.get("feed", {}).get("binance", {})
        assets = {k: v for k, v in feed.items() if isinstance(v, dict)}

        btc_series = [float(x) for x in assets.get("BTC", {}).get("v60s_series", [])][-30:]
        eth_series = [float(x) for x in assets.get("ETH", {}).get("v60s_series", [])][-30:]
        sol_series = [float(x) for x in assets.get("SOL", {}).get("v60s_series", [])][-30:]
        xrp_series = [float(x) for x in assets.get("XRP", {}).get("v60s_series", [])][-30:]
        if not btc_series:
            return {"regime": "RANGING", "trend_score": 0.5, "volatility_ratio": 1.0, "avg_correlation": 0.8}

        trend_score = sum(1 for v in btc_series if v > 0) / len(btc_series)
        current_abs = mean(abs(v) for v in btc_series)
        baseline = float(snapshot.get("baseline", {}).get("btc_avg_velocity", current_abs)) or current_abs
        volatility_ratio = current_abs / max(baseline, 1e-9)
        corr_eth = self._corr(btc_series, eth_series)
        corr_sol = self._corr(btc_series, sol_series)
        avg_corr = mean([corr_eth, corr_sol]) if eth_series and sol_series else 0.8

        btc_v = btc_series[-1] if btc_series else 0.0
        xrp_v = xrp_series[-1] if xrp_series else 0.0
        xrp_independent = abs(xrp_v) > 2.5 * abs(btc_v) and avg_corr < 0.5

        vol_ratio = float(assets.get("BTC", {}).get("volume_ratio_300_1800", 1.0))
        if xrp_independent:
            regime = "NEWS_DRIVEN"
        elif volatility_ratio > 2.5:
            regime = "VOLATILE"
        elif vol_ratio > 3.0:
            regime = "NEWS_DRIVEN"
        elif volatility_ratio < 0.4:
            regime = "QUIET"
        elif trend_score > 0.70:
            regime = "TRENDING_UP"
        elif trend_score < 0.30:
            regime = "TRENDING_DOWN"
        elif avg_corr < 0.4:
            regime = "DECORRELATED"
        else:
            regime = "RANGING"

        return {
            "regime": regime,
            "trend_score": round(trend_score, 4),
            "volatility_ratio": round(volatility_ratio, 4),
            "avg_correlation": round(avg_corr, 4),
        }

    def _append_history(self, row: dict[str, float | str]) -> None:
        try:
            history = json.loads(self.history_path.read_text())
            history.append(row)
            self.history_path.write_text(json.dumps(history[-1000:], indent=2))
        except Exception as exc:  # noqa: BLE001
            logger.warning("regime_history_write_failed", error=str(exc))

    async def run(self) -> None:
        """Classify every 60 seconds and publish change events."""
        while True:
            try:
                result = await self._classify()
                old = str(await self.state.get("bot", "current_regime", default="RANGING"))
                new = str(result["regime"])
                now = time.time()

                await self.state.set("regime", value=result)
                bot = await self.state.get("bot", default={})
                bot["current_regime"] = new
                await self.state.set("bot", value=bot)

                if new != old:
                    duration = int(now - self._regime_since)
                    self._regime_since = now
                    await bus.publish("REGIME_CHANGED", {"old": old, "new": new, **result, "duration_seconds": duration})
                    self._append_history({"timestamp": now, "regime": new, **result, "duration_seconds": duration})
            except Exception as exc:  # noqa: BLE001
                logger.warning("regime_detector_error", error=str(exc))
            await asyncio.sleep(60)
