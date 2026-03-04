from trading.sizing import calculate_bet_size


def test_kelly_sizing_respects_minimum():
    size = calculate_bet_size(
        bankroll=50.0,
        entry_price=0.12,
        confidence=0.52,
        win_rate_10=0.40,
        consecutive_losses=6,
        asset="XRP",
    )
    assert size >= 1.0


def test_kelly_sizing_respects_max_cap():
    bankroll = 200.0
    size = calculate_bet_size(
        bankroll=bankroll,
        entry_price=0.08,
        confidence=0.95,
        win_rate_10=0.9,
        consecutive_losses=0,
        asset="SOL",
    )
    assert size <= bankroll * 0.15
