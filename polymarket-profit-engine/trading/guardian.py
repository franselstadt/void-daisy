"""Pre-trade safety gate."""

from __future__ import annotations

from core.config import config
from core.state import state


def check(opp: dict) -> tuple[bool, str]:
    asset = opp['asset']
    if state.get('bot.emergency_stopped', False):
        return False, 'EMERGENCY_STOPPED'
    if state.get('bot.hard_stopped', False):
        return False, 'HARD_STOPPED'
    if state.get('bot.paused', False):
        return False, 'PAUSED'
    bankroll = float(state.get('stats.bankroll', state.get('bankroll', 0.0)))
    if bankroll < 10:
        return False, 'BANKROLL_CRITICAL'

    level = int(state.get('bot.degradation_level', state.get('degradation_level', 0)))
    if level == 3 and opp.get('plan') != 'PLAN_02':
        return False, 'SURVIVAL_ORACLE_ONLY'

    positions = list(state.get('positions.open', []))
    if len(positions) >= 4:
        return False, 'MAX_POSITIONS'
    if state.get(f'position.open.{asset}', False):
        return False, 'ASSET_ALREADY_OPEN'

    open_exp = float(state.get('stats.open_exposure', 0.0))
    if open_exp + float(opp.get('bet_size', 0.0)) > bankroll * 0.40:
        return False, 'EXPOSURE_LIMIT'

    if float(opp.get('confidence', 0.0)) < (float(config.get('trading', 'min_confidence', default=0.62)) + (0.03 * level)):
        return False, 'CONFIDENCE_LOW'
    if float(opp.get('exhaustion_score', 0.0)) < (float(config.get('trading', 'min_exhaustion', default=3.5)) + (0.3 * level)):
        return False, 'EXHAUSTION_LOW'

    if asset == 'XRP' and state.get('xrp.news_blackout_active', False):
        return False, 'XRP_BLACKOUT'

    major_all = all(abs(float(state.get(f'price.{a}.pct_change_60s', 0.0))) > 0.003 for a in ['BTC', 'ETH', 'SOL', 'XRP'])
    if major_all:
        return False, 'MACRO_EVENT'

    if not state.get(f'feed.binance.{asset}.connected', False):
        return False, 'BINANCE_DOWN'
    if not state.get('feed.polymarket.connected', False):
        return False, 'POLYMARKET_DOWN'

    return True, 'OK'
