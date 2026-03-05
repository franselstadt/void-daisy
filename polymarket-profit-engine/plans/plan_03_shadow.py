from plans.base import BasePlan
from core.state import state


class Plan03Shadow(BasePlan):
    name = 'PLAN_03'

    def evaluate(self, ctx):
        asset = ctx['asset']
        if asset == 'BTC':
            return None
        btc_v30 = ctx.get('btc_v30', 0.0)
        if abs(btc_v30) < 0.0001:
            return None
        lag_score = ctx.get('lag_score', 0.0)
        if lag_score < 0.05:
            return None
        secs = ctx['seconds_remaining']
        if secs < 80 or secs > 270:
            return None
        v30 = ctx.get('v30', 0.0)
        if (btc_v30 > 0 and v30 < 0) or (btc_v30 < 0 and v30 > 0):
            return None
        corr_strength = ctx.get('correlation_strength', 0.7)
        if corr_strength < 0.6:
            return None
        d = 'UP' if btc_v30 > 0 else 'DOWN'
        e = ctx['yes_price'] if d == 'UP' else ctx['no_price']
        c = max(0.58, min(0.9, ctx['confidence']))
        edge = (c * 0.28) - ((1 - c) * e)
        return self._mk(ctx, d, e, c, ctx['exhaustion_score'], edge, edge, ctx['signals_fired'])
