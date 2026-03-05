from plans.base import BasePlan

class Plan01DeadCat(BasePlan):
    name='PLAN_01'
    def evaluate(self, ctx):
        yes,no=ctx['yes_price'],ctx['no_price']
        d='UP' if 0.04<=yes<=0.16 else 'DOWN' if 0.04<=no<=0.16 else ''
        if not d or ctx['exhaustion_score']<3.5 or ctx['seconds_remaining']<100 or ctx['spread']>0.05: return None
        e=yes if d=='UP' else no
        c=max(0.62, min(0.95, ctx['confidence']))
        edge=(c*0.38)-((1-c)*e)
        return self._mk(ctx,d,e,c,ctx['exhaustion_score'],edge,edge*1.2,ctx['signals_fired'])
