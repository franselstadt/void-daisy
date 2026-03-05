import pytest

from core.event_bus import bus
from core.state import AppState
from trading.profit_taker import ProfitTaker


@pytest.mark.asyncio
async def test_profit_taker_emits_exit_on_stop_loss(monkeypatch):
    state = AppState()
    await state.set(
        "open_positions",
        value={
            "BTC": {
                "asset": "BTC",
                "direction": "UP",
                "entry_price": 0.1,
                "bet_size": 10.0,
                "shares": 100.0,
                "market_id": "m1",
                "signal_scores": {},
            }
        },
    )

    emitted = []

    async def fake_publish(event_type, data):
        emitted.append((event_type, data))

    monkeypatch.setattr(bus, "publish", fake_publish)

    taker = ProfitTaker(state)
    await taker.on_tick(
        {
            "asset": "BTC",
            "yes_price": 0.02,
            "no_price": 0.98,
            "seconds_remaining": 120,
            "velocity_10s": 0.0,
            "velocity_30s": 0.0,
            "volume_ratio": 1.0,
            "orderbook": {"bids_volume": 1, "asks_volume": 1},
        }
    )

    assert emitted
    assert emitted[0][0] == "TRADE_EXIT_REQUEST"
    assert emitted[0][1]["reason"] == "STOP_LOSS_HIT"
