from plans.base import BasePlan

class Plan04TrendRider(BasePlan):
    name='PLAN_04'
    def evaluate(self, ctx):
        yes=ctx['yes_price']
        if not (0.35<=yes<=0.65): return None
        if abs(ctx.get('v30',0.0))<0.0004 or ctx['seconds_remaining']<150: return None
        d='UP' if ctx.get('v30',0.0)>0 else 'DOWN'
        e=yes if d=='UP' else ctx['no_price']
        c=max(0.68,min(0.95,ctx['confidence']))
        edge=(c*0.55)-((1-c)*e)
        return self._mk(ctx,d,e,c,ctx['exhaustion_score'],edge,edge*1.5,ctx['signals_fired'])
