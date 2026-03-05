from plans.base import BasePlan
from core.state import state


class Plan10CorrelatedCollapse(BasePlan):
    name = 'PLAN_10'

    def evaluate(self, ctx):
        secs = ctx['seconds_remaining']
        if secs < 90 or secs > 220:
            return None
        crashing = 0
        for a in ['BTC', 'ETH', 'SOL', 'XRP']:
            v = float(state.get(f'price.{a}.velocity_30s', 0.0))
            if v < -0.002:
                crashing += 1
        if crashing < 3:
            return None
        btc_vol = float(state.get('price.BTC.volume_ratio_10_60', 1.0))
        if btc_vol < 2.0:
            return None
        asset = ctx['asset']
        asset_crash = abs(float(state.get(f'price.{asset}.velocity_30s', 0.0)))
        btc_crash = abs(float(state.get('price.BTC.velocity_30s', 0.0)))
        if asset_crash > btc_crash:
            return None
        d = 'DOWN'
        e = ctx['no_price']
        c = max(0.65, min(0.95, ctx['confidence']))
        edge = (c * 0.45) - ((1 - c) * e)
        return self._mk(ctx, d, e, c, ctx['exhaustion_score'], edge, edge * 1.3, ctx['signals_fired'])
