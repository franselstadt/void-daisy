from risk.degrader import Degrader


def test_degrader_levels():
    d = Degrader()
    assert d.evaluate(0, 0.0, 0.6) == 0
    assert d.evaluate(3, 0.0, 0.6) == 1
    assert d.evaluate(5, 0.0, 0.6) == 2
    assert d.evaluate(7, 0.0, 0.6) == 3
