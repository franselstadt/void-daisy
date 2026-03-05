from plans.base import BasePlan

class Plan08NewsFade(BasePlan):
    name='PLAN_08'
    def evaluate(self, ctx):
        if ctx.get('regime')!='NEWS_DRIVEN': return None
        if ctx['seconds_remaining']<120: return None
        d='UP' if ctx.get('v10',0)<0 else 'DOWN'
        e=ctx['yes_price'] if d=='UP' else ctx['no_price']
        c=max(0.58,min(0.88,ctx['confidence']))
        edge=(c*0.22)-((1-c)*e)
        return self._mk(ctx,d,e,c,ctx['exhaustion_score'],edge,edge*0.9,ctx['signals_fired'])
