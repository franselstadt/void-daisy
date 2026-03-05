"""Rule-based market regime detector."""

from __future__ import annotations

import asyncio
from statistics import mean

import numpy as np

from core.event_bus import bus
from core.state import state


def _corr(a: list[float], b: list[float]) -> float:
    if len(a) < 5 or len(b) < 5:
        return 0.8
    try:
        return float(np.corrcoef(np.array(a[-30:]), np.array(b[-30:]))[0, 1])
    except Exception:
        return 0.8


class RegimeDetector:
    async def run(self) -> None:
        while True:
            btc = list(state.get('history.BTC.velocity_60s', []))[-30:]
            eth = list(state.get('history.ETH.velocity_60s', []))[-30:]
            sol = list(state.get('history.SOL.velocity_60s', []))[-30:]
            xrp = list(state.get('history.XRP.velocity_60s', []))[-30:]
            if not btc:
                await asyncio.sleep(60)
                continue
            trend = sum(1 for v in btc if v > 0) / len(btc)
            cur_abs = mean(abs(v) for v in btc)
            baseline = float(state.get('baseline.btc_avg_velocity', cur_abs) or cur_abs)
            if baseline <= 0:
                baseline = cur_abs or 1e-9
            vol_ratio = cur_abs / baseline
            state.set_sync('baseline.btc_avg_velocity', (baseline * 0.95) + (cur_abs * 0.05))
            vol_regime = float(state.get('price.BTC.volume_ratio_60_300', 1.0))
            c1 = _corr(btc, eth)
            c2 = _corr(btc, sol)
            avg_corr = (c1 + c2) / 2
            xrp_v = xrp[-1] if xrp else 0.0
            btc_v = btc[-1] if btc else 0.0
            xrp_ind = abs(xrp_v) > 2.5 * abs(btc_v) and avg_corr < 0.5

            if xrp_ind:
                regime = 'NEWS_DRIVEN'
            elif vol_ratio > 2.5:
                regime = 'VOLATILE'
            elif vol_regime > 3.0:
                regime = 'NEWS_DRIVEN'
            elif vol_ratio < 0.4:
                regime = 'QUIET'
            elif trend > 0.70:
                regime = 'TRENDING_UP'
            elif trend < 0.30:
                regime = 'TRENDING_DOWN'
            elif avg_corr < 0.4:
                regime = 'DECORRELATED'
            else:
                regime = 'RANGING'

            old = state.get('bot.current_regime', 'RANGING')
            state.set_sync('bot.current_regime', regime)
            state.set_sync('bot.regime_confidence', 0.75)
            state.set_sync('regime.trend_score', trend)
            state.set_sync('regime.volatility_ratio', vol_ratio)
            state.set_sync('regime.avg_correlation', avg_corr)
            if old != regime:
                await bus.publish('REGIME_CHANGED', {'old': old, 'new': regime, 'trend_score': trend, 'volatility_ratio': vol_ratio, 'avg_correlation': avg_corr})
            await asyncio.sleep(60)
