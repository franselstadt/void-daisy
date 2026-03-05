from plans.base import BasePlan


class Plan09WindowOpen(BasePlan):
    name = 'PLAN_09'

    def evaluate(self, ctx):
        elapsed = ctx.get('window_elapsed', 999)
        if elapsed > 65:
            return None
        regime = ctx.get('regime', 'RANGING')
        if regime not in {'TRENDING_UP', 'TRENDING_DOWN'}:
            return None
        secs = ctx['seconds_remaining']
        if secs < 235:
            return None
        v30 = ctx.get('v30', 0.0)
        if abs(v30) < 0.002:
            return None
        kalman_v = ctx.get('kalman_velocity', v30)
        if (v30 > 0 and kalman_v < 0) or (v30 < 0 and kalman_v > 0):
            return None
        vol_ratio = ctx.get('vol_ratio', 1.0)
        if vol_ratio < 1.5:
            return None
        yes = ctx['yes_price']
        if not (0.40 <= yes <= 0.60):
            return None
        d = 'UP' if v30 > 0 else 'DOWN'
        e = yes if d == 'UP' else ctx['no_price']
        c = max(0.57, min(0.86, ctx['confidence']))
        edge = (c * 0.40) - ((1 - c) * e)
        return self._mk(ctx, d, e, c, ctx['exhaustion_score'], edge, edge * 0.8, ctx['signals_fired'])
