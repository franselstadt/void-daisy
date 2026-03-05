from plans.base import BasePlan
from core.state import state


class Plan11SpreadCompression(BasePlan):
    name = 'PLAN_11'

    def evaluate(self, ctx):
        spread = ctx.get('spread', 1.0)
        normal_spread = 0.03
        if spread < normal_spread * 2.0:
            return None
        secs = ctx['seconds_remaining']
        if secs < 80 or secs > 240:
            return None
        imb = ctx.get('order_imbalance', 0)
        if abs(imb) < 0.25:
            return None
        d = 'UP' if imb > 0.25 else 'DOWN'
        e = ctx['yes_price'] if d == 'UP' else ctx['no_price']
        c = max(0.6, min(0.9, ctx['confidence']))
        edge = (c * 0.20) - ((1 - c) * e)
        return self._mk(ctx, d, e, c, ctx['exhaustion_score'], edge, edge, ctx['signals_fired'])
