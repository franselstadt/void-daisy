from plans.base import BasePlan

class Plan11SpreadCompression(BasePlan):
    name='PLAN_11'
    def evaluate(self, ctx):
        if ctx.get('spread',1.0)>0.03: return None
        if ctx.get('prev_spread',1.0)<=0 or ctx['spread']>=ctx['prev_spread']*0.8: return None
        d='UP' if ctx.get('order_imbalance',0)>0 else 'DOWN'
        e=ctx['yes_price'] if d=='UP' else ctx['no_price']
        c=max(0.6,min(0.9,ctx['confidence']))
        edge=(c*0.24)-((1-c)*e)
        return self._mk(ctx,d,e,c,ctx['exhaustion_score'],edge,edge,ctx['signals_fired'])
