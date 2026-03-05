from core.state import state
from trading.guardian import check


def test_guardian_blocks_paused():
    state.set_sync('bot.paused', True)
    ok, reason = check({'asset': 'BTC', 'plan': 'PLAN_01', 'confidence': 0.9, 'exhaustion_score': 5.0, 'bet_size': 1.0})
    assert not ok
    assert reason == 'PAUSED'
    state.set_sync('bot.paused', False)
