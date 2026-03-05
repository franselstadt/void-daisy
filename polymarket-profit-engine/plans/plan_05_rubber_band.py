from plans.base import BasePlan

class Plan05RubberBand(BasePlan):
    name='PLAN_05'
    def evaluate(self, ctx):
        y=ctx['yes_price']; reg=ctx.get('regime','RANGING')
        if reg not in {'RANGING','QUIET'}: return None
        if not ((0.17<=y<=0.35) or (0.65<=y<=0.83)): return None
        d='UP' if y<=0.35 else 'DOWN'
        e=y if d=='UP' else ctx['no_price']
        c=max(0.60,min(0.9,ctx['confidence']))
        edge=(c*0.28)-((1-c)*e)
        return self._mk(ctx,d,e,c,ctx['exhaustion_score'],edge,edge,ctx['signals_fired'])
