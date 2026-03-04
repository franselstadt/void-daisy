import json

import pytest

from core.config import ConfigManager
from core.state import AppState
from trading.guardian import TradeGuardian


@pytest.mark.asyncio
async def test_guardian_blocks_paused_bot(tmp_path):
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({"trading": {"max_positions": 2, "min_edge_pct": 0.15, "min_exhaustion": 3.5, "min_seconds": 120, "max_seconds": 270, "max_spread": 0.04}}))
    cfg = ConfigManager(cfg_path)

    state = AppState()
    bot = await state.get("bot", default={})
    bot["paused"] = True
    await state.set("bot", value=bot)

    guardian = TradeGuardian(state, cfg)
    allowed, reason = await guardian.check(
        {
            "asset": "BTC",
            "edge_pct": 0.3,
            "exhaustion_score": 5.0,
            "seconds_remaining": 180,
            "spread": 0.01,
        },
        {"confidence_bonus": 0.0, "exhaustion_bonus": 0.0},
    )

    assert not allowed
    assert reason == "paused"
