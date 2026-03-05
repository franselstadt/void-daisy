from plans.base import BasePlan

class Plan03Shadow(BasePlan):
    name='PLAN_03'
    def evaluate(self, ctx):
        if ctx.get('spread',1.0)>0.035 or abs(ctx.get('v10',0.0))>abs(ctx.get('v30',0.0)): return None
        d='UP' if ctx.get('v30',0.0)>0 else 'DOWN'
        e=ctx['yes_price'] if d=='UP' else ctx['no_price']
        c=max(0.58, min(0.9, ctx['confidence']))
        edge=(c*0.24)-((1-c)*e)
        return self._mk(ctx,d,e,c,ctx['exhaustion_score'],edge,edge,ctx['signals_fired'])
