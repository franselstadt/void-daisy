from plans.base import BasePlan

class Plan09WindowOpen(BasePlan):
    name='PLAN_09'
    def evaluate(self, ctx):
        if ctx.get('window_elapsed',999)>60: return None
        if abs(ctx.get('v30',0.0))<0.0003: return None
        d='UP' if ctx.get('v30',0)>0 else 'DOWN'
        e=ctx['yes_price'] if d=='UP' else ctx['no_price']
        c=max(0.57,min(0.86,ctx['confidence']))
        edge=(c*0.20)-((1-c)*e)
        return self._mk(ctx,d,e,c,ctx['exhaustion_score'],edge,edge*0.8,ctx['signals_fired'])
