from plans.base import BasePlan


class Plan06WhaleFade(BasePlan):
    name = 'PLAN_06'

    def evaluate(self, ctx):
        if not ctx.get('whale', False):
            return None
        secs = ctx['seconds_remaining']
        if secs < 90 or secs > 240:
            return None
        imb = ctx.get('order_imbalance', 0)
        d = 'DOWN' if imb > 0.25 else 'UP' if imb < -0.25 else ''
        if not d:
            return None
        e = ctx['yes_price'] if d == 'UP' else ctx['no_price']
        c = max(0.61, min(0.9, ctx['confidence']))
        edge = (c * 0.25) - ((1 - c) * e)
        return self._mk(ctx, d, e, c, ctx['exhaustion_score'], edge, edge, ctx['signals_fired'])
