from plans.base import BasePlan


class Plan01DeadCat(BasePlan):
    name = 'PLAN_01'

    def evaluate(self, ctx):
        yes, no = ctx['yes_price'], ctx['no_price']
        d = 'UP' if 0.05 <= yes <= 0.13 else 'DOWN' if 0.05 <= no <= 0.13 else ''
        if not d:
            return None
        if ctx['exhaustion_score'] < 3.5:
            return None
        secs = ctx['seconds_remaining']
        if secs < 100 or secs > 215:
            return None
        if ctx['spread'] > 0.05:
            return None
        v10 = abs(ctx.get('v10', 0.0))
        v30 = abs(ctx.get('v30', 0.0))
        if v30 > 0 and v10 > v30 * 0.6:
            return None
        rsi = ctx.get('rsi', 50.0)
        if d == 'UP' and rsi > 30:
            return None
        if d == 'DOWN' and rsi < 70:
            return None
        e = yes if d == 'UP' else no
        c = max(0.62, min(0.95, ctx['confidence']))
        edge = (c * 0.38) - ((1 - c) * e)
        return self._mk(ctx, d, e, c, ctx['exhaustion_score'], edge, edge * 1.2, ctx['signals_fired'])
