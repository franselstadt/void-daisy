from plans.base import BasePlan


class Plan05RubberBand(BasePlan):
    name = 'PLAN_05'

    def evaluate(self, ctx):
        reg = ctx.get('regime', 'RANGING')
        if reg not in {'RANGING', 'QUIET'}:
            return None
        y = ctx['yes_price']
        if not ((0.17 <= y <= 0.32) or (0.68 <= y <= 0.83)):
            return None
        secs = ctx['seconds_remaining']
        if secs < 150:
            return None
        v10, v30 = abs(ctx.get('v10', 0.0)), abs(ctx.get('v30', 0.0))
        if v30 > 0 and v10 > v30:
            return None
        vol_ratio = ctx.get('vol_ratio', 1.0)
        if vol_ratio > 1.2:
            return None
        if ctx.get('spread', 1.0) > 0.04:
            return None
        d = 'UP' if y <= 0.32 else 'DOWN'
        e = y if d == 'UP' else ctx['no_price']
        c = max(0.60, min(0.9, ctx['confidence']))
        edge = (c * 0.28) - ((1 - c) * e)
        return self._mk(ctx, d, e, c, ctx['exhaustion_score'], edge, edge, ctx['signals_fired'])
