from plans.base import BasePlan
from core.state import state


class Plan08NewsFade(BasePlan):
    name = 'PLAN_08'

    def evaluate(self, ctx):
        asset = ctx['asset']
        if state.get(f'{asset.lower()}.news_blackout_active', False):
            return None
        secs = ctx['seconds_remaining']
        if secs < 120 or secs > 250:
            return None
        asset_v30 = abs(ctx.get('v30', 0.0))
        btc_v30 = abs(ctx.get('btc_v30', 0.0))
        if btc_v30 > 0 and asset_v30 / max(btc_v30, 1e-9) < 3.0:
            return None
        vol_ratio = ctx.get('vol_ratio', 1.0)
        if vol_ratio < 3.0:
            return None
        v10 = abs(ctx.get('v10', 0.0))
        v30 = abs(ctx.get('v30', 0.0))
        if v30 > 0 and v10 > v30:
            return None
        d = 'UP' if ctx.get('v10', 0) < 0 else 'DOWN'
        e = ctx['yes_price'] if d == 'UP' else ctx['no_price']
        c = max(0.58, min(0.88, ctx['confidence']))
        edge = (c * 0.30) - ((1 - c) * e)
        return self._mk(ctx, d, e, c, ctx['exhaustion_score'], edge, edge * 0.9, ctx['signals_fired'])
