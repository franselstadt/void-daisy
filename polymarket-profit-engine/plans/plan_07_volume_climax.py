from plans.base import BasePlan

class Plan07VolumeClimax(BasePlan):
    name='PLAN_07'
    def evaluate(self, ctx):
        if ctx.get('vol_ratio',1.0)<2.5: return None
        d='DOWN' if ctx.get('buy_pct',0.5)>0.8 else 'UP' if ctx.get('buy_pct',0.5)<0.2 else ''
        if not d: return None
        e=ctx['yes_price'] if d=='UP' else ctx['no_price']
        c=max(0.63,min(0.92,ctx['confidence']))
        edge=(c*0.30)-((1-c)*e)
        return self._mk(ctx,d,e,c,ctx['exhaustion_score'],edge,edge,ctx['signals_fired'])
