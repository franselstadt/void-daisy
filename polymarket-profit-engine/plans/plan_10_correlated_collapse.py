from plans.base import BasePlan

class Plan10CorrelatedCollapse(BasePlan):
    name='PLAN_10'
    def evaluate(self, ctx):
        if not ctx.get('cross_asset_ok',False): return None
        if ctx.get('lag_score',0.0)<0.05: return None
        d='UP' if ctx.get('btc_v30',0)>0 else 'DOWN'
        e=ctx['yes_price'] if d=='UP' else ctx['no_price']
        c=max(0.65,min(0.95,ctx['confidence']))
        edge=(c*0.34)-((1-c)*e)
        return self._mk(ctx,d,e,c,ctx['exhaustion_score'],edge,edge*1.3,ctx['signals_fired'])
