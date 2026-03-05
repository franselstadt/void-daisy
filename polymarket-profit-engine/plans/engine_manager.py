"""Runs all 12 plans every polymarket tick."""

from __future__ import annotations

import asyncio
import time

from core.event_bus import bus
from core.logger import logger
from core.state import state
from signals.exhaustion import exhaustion_engine
from signals.orderbook import imbalance, whale_detected

from plans.plan_01_dead_cat import Plan01DeadCat
from plans.plan_02_oracle_knife import Plan02OracleKnife
from plans.plan_03_shadow import Plan03Shadow
from plans.plan_04_trend_rider import Plan04TrendRider
from plans.plan_05_rubber_band import Plan05RubberBand
from plans.plan_06_whale_fade import Plan06WhaleFade
from plans.plan_07_volume_climax import Plan07VolumeClimax
from plans.plan_08_news_fade import Plan08NewsFade
from plans.plan_09_window_open import Plan09WindowOpen
from plans.plan_10_correlated_collapse import Plan10CorrelatedCollapse
from plans.plan_11_spread_compression import Plan11SpreadCompression
from plans.plan_12_scheduled_coverage import Plan12ScheduledCoverage


class EngineManager:
    def __init__(self) -> None:
        self.plans = [
            Plan01DeadCat(), Plan02OracleKnife(), Plan03Shadow(), Plan04TrendRider(), Plan05RubberBand(), Plan06WhaleFade(),
            Plan07VolumeClimax(), Plan08NewsFade(), Plan09WindowOpen(), Plan10CorrelatedCollapse(), Plan11SpreadCompression(), Plan12ScheduledCoverage(),
        ]

    def _context(self, event: dict) -> dict:
        asset = event['asset']
        bid = float(event.get('orderbook', {}).get('bids_volume', 0.0) or 0.0)
        ask = float(event.get('orderbook', {}).get('asks_volume', 0.0) or 0.0)
        order_imb = imbalance(bid, ask)
        whale = whale_detected(float(event.get('orderbook', {}).get('largest_order', 0.0) or 0.0), bid + ask)

        v10 = float(state.get(f'price.{asset}.velocity_10s', 0.0))
        v30 = float(state.get(f'price.{asset}.velocity_30s', 0.0))
        v60 = float(state.get(f'price.{asset}.velocity_60s', 0.0))
        btc_v30 = float(state.get('price.BTC.velocity_30s', 0.0))
        accel = float(state.get(f'price.{asset}.acceleration', 0.0))
        consecutive = int(state.get(f'price.{asset}.consecutive_direction', 0))
        spot = float(state.get(f'price.{asset}.price', 0.0))
        rsi = float(state.get(f'price.{asset}.rsi_14', 50.0))

        direction = 'UP' if v30 > 0 else 'DOWN' if v30 < 0 else 'FLAT'
        prev_bid = float(state.get(f'polymarket.prev.{asset}.bid_depth', bid))
        bid_depth_delta = bid - prev_bid
        round_number = round(spot / 1000) * 1000 if spot > 100 else round(spot, 1)
        round_prox = abs(spot - round_number) / max(spot, 1e-9) < 0.01 if spot > 0 else False
        btc_led = abs(btc_v30) > abs(v30) * 1.5 and ((btc_v30 > 0 and v30 >= 0) or (btc_v30 < 0 and v30 <= 0))
        xasset_div = abs(v30 - btc_v30 * 0.5) if btc_v30 != 0 else 0.0
        candles = abs(consecutive)

        ctx = {
            'asset': asset,
            'yes_price': float(event.get('yes_price', 0.5)),
            'no_price': float(event.get('no_price', 0.5)),
            'spread': float(event.get('spread', 1.0)),
            'prev_spread': float(state.get(f'polymarket.prev.{asset}.spread', event.get('spread', 1.0))),
            'lag_score': float(event.get('lag_score', 0.0)),
            'seconds_remaining': int(event.get('seconds_remaining', 0)),
            'window_elapsed': int(event.get('window_elapsed', 0)),
            'market_id': str(event.get('market_id', '')),
            'token_id': str(event.get('token_id', '')),
            'timestamp': float(event.get('timestamp', time.time())),
            'v10': v10,
            'v30': v30,
            'v60': v60,
            'v300': float(state.get(f'price.{asset}.velocity_300s', 0.0)),
            'btc_v30': btc_v30,
            'accel': accel,
            'vol_ratio': float(state.get(f'price.{asset}.volume_ratio_10_60', 1.0)),
            'vol_ratio_60_300': float(state.get(f'price.{asset}.volume_ratio_60_300', 1.0)),
            'buy_pct': float(state.get(f'price.{asset}.buy_volume_pct', 0.5)),
            'rsi': rsi,
            'vwap_dev': float(state.get(f'price.{asset}.vwap_deviation', 0.0)),
            'oracle_lag': float(state.get(f'oracle.{asset}.lag_seconds', 0.0)),
            'oracle_delta': float(state.get(f'oracle.{asset}.delta_pct', 0.0)),
            'oracle_direction': str(state.get(f'oracle.{asset}.direction', 'FLAT')),
            'regime': str(state.get('bot.current_regime', 'RANGING')),
            'order_imbalance': order_imb,
            'whale': whale,
            'direction': direction,
            'bid_depth_delta': bid_depth_delta,
            'round_prox': round_prox,
            'btc_led': btc_led,
            'xasset_div': xasset_div,
            'candles': candles,
            'consecutive_direction': consecutive,
            'kalman_price': float(state.get(f'price.{asset}.kalman_price', spot)),
            'kalman_velocity': float(state.get(f'price.{asset}.kalman_velocity', v30)),
            'cross_asset_ok': abs(v30) > 0 and abs(btc_v30) > 0,
            'correlation_lag': float(state.get(f'correlation.lag.{asset}', 10.0)),
            'correlation_strength': float(state.get(f'correlation.strength.{asset}', 0.7)),
        }
        ex = exhaustion_engine.score(ctx)
        ctx['exhaustion_score'] = ex['score']
        ctx['signals_fired'] = ex['signals_fired']
        conf = min(0.99, max(0.0, (ex['score'] / 10) * 0.45 + min(1.0, abs(ctx['v30']) * 1000) * 0.25 + min(1.0, ctx['lag_score'] * 8) * 0.2 + (0.1 if whale else 0.0)))
        ctx['confidence'] = conf
        return ctx

    def evaluate_all(self, ctx: dict, relax_threshold: bool = False) -> list[dict]:
        """Evaluate every plan and return opportunities sorted by EV."""
        opportunities: list[dict] = []
        for p in self.plans:
            opp = p.evaluate(ctx)
            if not opp:
                continue
            if relax_threshold:
                if float(opp.confidence) < 0.55 or float(opp.exhaustion_score) < 2.5:
                    continue
            opportunities.append(opp.to_dict())
        return sorted(opportunities, key=lambda x: float(x.get('ev', 0.0)), reverse=True)

    def evaluate_asset(self, asset: str, relax_threshold: bool = False) -> list[dict]:
        """Build context from latest state and evaluate all plans."""
        event = {
            'asset': asset,
            'yes_price': float(state.get(f'polymarket.{asset}.yes_price', 0.5)),
            'no_price': float(state.get(f'polymarket.{asset}.no_price', 0.5)),
            'spread': float(state.get(f'polymarket.{asset}.spread', 1.0)),
            'lag_score': float(state.get(f'polymarket.{asset}.lag_score', 0.0)),
            'seconds_remaining': int(state.get(f'polymarket.{asset}.seconds_remaining', 0)),
            'window_elapsed': int(state.get(f'polymarket.{asset}.window_elapsed', 0)),
            'market_id': str(state.get(f'polymarket.{asset}.market_id', '')),
            'token_id': str(state.get(f'polymarket.{asset}.token_id', '')),
            'orderbook': {},
            'timestamp': float(state.get(f'polymarket.{asset}.timestamp', time.time())),
        }
        return self.evaluate_all(self._context(event), relax_threshold=relax_threshold)

    async def on_poly_tick(self, event: dict) -> None:
        try:
            ctx = self._context(event)
            opps = self.evaluate_all(ctx, relax_threshold=False)
            if not opps:
                opps = self.evaluate_all(ctx, relax_threshold=True)
            for opp in opps:
                await bus.publish('OPPORTUNITY_DETECTED', opp)
            state.set_sync(f'polymarket.prev.{event["asset"]}.spread', float(event.get('spread', 0.0)))
            state.set_sync(f'polymarket.prev.{event["asset"]}.bid_depth', float(event.get('orderbook', {}).get('bids_volume', 0.0) or 0.0))
        except Exception as exc:  # noqa: BLE001
            logger.warning('engine_manager_error', error=str(exc))

    async def run(self) -> None:
        exhaustion_engine.start()
        bus.subscribe('POLYMARKET_TICK', self.on_poly_tick)
        while True:
            await asyncio.sleep(3600)
