from plans.base import BasePlan


class Plan07VolumeClimax(BasePlan):
    name = 'PLAN_07'

    def evaluate(self, ctx):
        vol_ratio = ctx.get('vol_ratio', 1.0)
        if vol_ratio < 4.0:
            return None
        secs = ctx['seconds_remaining']
        if secs < 100 or secs > 240:
            return None
        rsi = ctx.get('rsi', 50.0)
        candles = ctx.get('candles', 0)
        buy_pct = ctx.get('buy_pct', 0.5)
        v10 = abs(ctx.get('v10', 0.0))
        v30 = abs(ctx.get('v30', 0.0))
        if v30 > 0 and v10 > v30:
            return None
        if rsi < 20 and candles >= 3:
            d = 'UP'
        elif rsi > 80 and candles >= 3:
            d = 'DOWN'
        elif buy_pct > 0.8:
            d = 'DOWN'
        elif buy_pct < 0.2:
            d = 'UP'
        else:
            return None
        e = ctx['yes_price'] if d == 'UP' else ctx['no_price']
        c = max(0.63, min(0.92, ctx['confidence']))
        edge = (c * 0.35) - ((1 - c) * e)
        return self._mk(ctx, d, e, c, ctx['exhaustion_score'], edge, edge, ctx['signals_fired'])
