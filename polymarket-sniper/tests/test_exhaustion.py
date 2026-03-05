from signals.exhaustion import ExhaustionScorer


def test_exhaustion_score_fires_expected_signals(tmp_path):
    weights = tmp_path / "weights.json"
    scorer = ExhaustionScorer(weights)

    out = scorer.score(
        {
            "direction": "UP",
            "velocity_10s": 0.0001,
            "velocity_30s": 0.001,
            "spread": 0.01,
            "prev_spread": 0.02,
            "volume_ratio": 0.4,
            "rsi_14": 20,
            "spot_price": 10000,
            "orderbook": {"bids_volume": 120, "asks_volume": 90},
            "btc_velocity_10s": 0.002,
            "oracle_lag_seconds": 3.0,
            "consecutive_candles": 4,
            "cross_asset_divergence": 0.2,
        }
    )

    assert out["score"] > 3.5
    assert "velocity_slowing" in out["signals_fired"]
    assert "rsi_oversold" in out["signals_fired"]
