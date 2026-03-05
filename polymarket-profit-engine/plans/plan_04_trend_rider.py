from plans.base import BasePlan


class Plan04TrendRider(BasePlan):
    name = 'PLAN_04'

    def evaluate(self, ctx):
        regime = ctx.get('regime', 'RANGING')
        if regime not in {'TRENDING_UP', 'TRENDING_DOWN'}:
            return None
        yes = ctx['yes_price']
        if not (0.38 <= yes <= 0.62):
            return None
        v10, v30, v60 = ctx.get('v10', 0.0), ctx.get('v30', 0.0), ctx.get('v60', 0.0)
        if abs(v30) < 0.0004:
            return None
        if not ((v10 > 0 and v30 > 0 and v60 > 0) or (v10 < 0 and v30 < 0 and v60 < 0)):
            return None
        secs = ctx['seconds_remaining']
        if secs < 150 or secs > 270:
            return None
        accel = ctx.get('accel', 0.0)
        if v30 > 0 and accel < 0:
            return None
        if v30 < 0 and accel > 0:
            return None
        vol_ratio = ctx.get('vol_ratio', 1.0)
        if vol_ratio < 1.2:
            return None
        buy_pct = ctx.get('buy_pct', 0.5)
        d = 'UP' if v30 > 0 else 'DOWN'
        if d == 'UP' and buy_pct < 0.60:
            return None
        if d == 'DOWN' and buy_pct > 0.40:
            return None
        e = yes if d == 'UP' else ctx['no_price']
        c = max(0.68, min(0.95, ctx['confidence']))
        edge = (c * 0.55) - ((1 - c) * e)
        return self._mk(ctx, d, e, c, ctx['exhaustion_score'], edge, edge * 1.5, ctx['signals_fired'])
