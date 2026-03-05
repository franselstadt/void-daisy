"""Multi-position tracking and state updates."""

from __future__ import annotations

import time
import uuid

from core.state import state


def open_position(trade: dict) -> None:
    asset = trade['asset']
    pid = str(uuid.uuid4())
    state.set_sync(f'position.open.{asset}', True)
    state.set_sync(f'position.{asset}.position_id', pid)
    state.set_sync(f'position.{asset}.plan', trade.get('plan'))
    state.set_sync(f'position.{asset}.direction', trade.get('direction'))
    state.set_sync(f'position.{asset}.entry_price', float(trade.get('entry_price', 0.0)))
    state.set_sync(f'position.{asset}.entry_time', time.time())
    state.set_sync(f'position.{asset}.shares', float(trade.get('shares', 0.0)))
    state.set_sync(f'position.{asset}.bet_size', float(trade.get('bet_size', 0.0)))
    state.set_sync(f'position.{asset}.stop_loss_price', 0.02)
    state.set_sync(f'position.{asset}.stop_moved_to_entry', False)
    state.set_sync(f'position.{asset}.high_watermark_price', float(trade.get('entry_price', 0.0)))
    state.set_sync(f'position.{asset}.market_id', trade.get('market_id', ''))
    state.set_sync(f'position.{asset}.token_id', trade.get('token_id', ''))
    pos = list(state.get('positions.open', []))
    if asset not in pos:
        pos.append(asset)
    state.set_sync('positions.open', pos)
    state.set_sync('stats.open_exposure', float(state.get('stats.open_exposure', 0.0)) + float(trade.get('bet_size', 0.0)))


def close_position(asset: str) -> None:
    bet = float(state.get(f'position.{asset}.bet_size', 0.0))
    state.set_sync(f'position.open.{asset}', False)
    pos = [a for a in state.get('positions.open', []) if a != asset]
    state.set_sync('positions.open', pos)
    state.set_sync('stats.open_exposure', max(0.0, float(state.get('stats.open_exposure', 0.0)) - bet))
