from trading.sizing import calculate_bet_size


def test_sizing_floor_and_cap():
    b = calculate_bet_size(200, 0.1, 0.9, 0.8, 0, 'BTC', 'PLAN_02', 0)
    assert b >= 1.0
    assert b <= 30.0
