from plans.base import BasePlan

class Plan06WhaleFade(BasePlan):
    name='PLAN_06'
    def evaluate(self, ctx):
        if not ctx.get('whale',False): return None
        d='DOWN' if ctx.get('order_imbalance',0)>0 else 'UP'
        e=ctx['yes_price'] if d=='UP' else ctx['no_price']
        c=max(0.61,min(0.9,ctx['confidence']))
        edge=(c*0.26)-((1-c)*e)
        return self._mk(ctx,d,e,c,ctx['exhaustion_score'],edge,edge,ctx['signals_fired'])
