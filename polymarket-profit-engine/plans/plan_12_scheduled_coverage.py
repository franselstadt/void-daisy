from plans.base import BasePlan

class Plan12ScheduledCoverage(BasePlan):
    name='PLAN_12'
    def evaluate(self, ctx):
        elapsed=ctx.get('window_elapsed',0)
        if not (120<=elapsed<=190): return None
        d='UP' if ctx.get('v30',0)>=0 else 'DOWN'
        e=ctx['yes_price'] if d=='UP' else ctx['no_price']
        c=max(0.55,min(0.82,ctx['confidence']))
        edge=(c*0.18)-((1-c)*e)
        return self._mk(ctx,d,e,c,ctx['exhaustion_score'],edge,edge*1.08,ctx['signals_fired'])
