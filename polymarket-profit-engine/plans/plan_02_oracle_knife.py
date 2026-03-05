from plans.base import BasePlan


class Plan02OracleKnife(BasePlan):
    name = 'PLAN_02'

    def evaluate(self, ctx):
        lag = ctx.get('oracle_lag', 0.0)
        delta = abs(ctx.get('oracle_delta', 0.0))
        if lag <= 2.5 or delta <= 0.003:
            return None
        if ctx.get('lag_score', 0.0) <= 0.05:
            return None
        v30 = ctx.get('v30', 0.0)
        oracle_dir = ctx.get('oracle_direction', 'FLAT')
        if oracle_dir == 'UP' and v30 < 0:
            return None
        if oracle_dir == 'DOWN' and v30 > 0:
            return None
        d = 'UP' if oracle_dir == 'UP' else 'DOWN'
        e = ctx['yes_price'] if d == 'UP' else ctx['no_price']
        c = max(0.75, min(0.99, ctx['confidence'] + 0.1))
        edge = (c * 0.30) - ((1 - c) * e)
        return self._mk(ctx, d, e, c, ctx['exhaustion_score'], edge, edge * 1.5, ctx['signals_fired'])
