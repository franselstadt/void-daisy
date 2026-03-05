"""Auto profit-taker checks all open positions every polymarket tick."""

from __future__ import annotations

from core.event_bus import bus
from core.state import state


def _green(asset: str, direction: str) -> int:
    g = 0
    v10 = float(state.get(f'price.{asset}.velocity_10s', 0.0))
    v30 = float(state.get(f'price.{asset}.velocity_30s', 0.0))
    vol = float(state.get(f'price.{asset}.volume_ratio_10_60', 1.0))
    if (direction == 'UP' and v10 > 0) or (direction == 'DOWN' and v10 < 0):
        g += 1
    if abs(v10) > abs(v30):
        g += 1
    if vol >= 0.8:
        g += 1
    if int(state.get(f'polymarket.{asset}.seconds_remaining', 0)) > 90:
        g += 1
    if abs(float(state.get(f'polymarket.{asset}.lag_score', 0.0))) > 0.02:
        g += 1
    return g


async def on_poly_tick(event: dict) -> None:
    asset = event['asset']
    if not state.get(f'position.open.{asset}', False):
        return

    plan = str(state.get(f'position.{asset}.plan', 'PLAN_01'))
    direction = str(state.get(f'position.{asset}.direction', 'UP'))
    entry = float(state.get(f'position.{asset}.entry_price', 0.0))
    shares = float(state.get(f'position.{asset}.shares', 0.0))
    bet = float(state.get(f'position.{asset}.bet_size', 0.0))
    cur = float(event['yes_price'] if direction == 'UP' else event['no_price'])
    secs = int(event.get('seconds_remaining', 0))
    pnl = ((shares * cur) - bet) / max(bet, 1e-9)

    reason = None
    if cur <= 0.02:
        reason = 'STOP_LOSS_HIT'
    elif secs <= 30:
        reason = 'TIME_30S'
    elif plan == 'PLAN_04' and pnl >= 0.75:
        reason = 'TARGET_REACHED'
    elif plan == 'PLAN_02' and (event.get('oracle_updated') or float(event.get('lag_score', 1.0)) < 0.02):
        reason = 'ORACLE_RESOLVED'
    elif plan in {'PLAN_01', 'PLAN_03', 'PLAN_05', 'PLAN_11'} and pnl >= 0.33:
        threshold = 3 if pnl < 0.5 else 4 if pnl < 0.7 else 5
        if _green(asset, direction) < threshold or pnl >= 0.85:
            reason = 'TAKE_PROFIT'
    elif plan == 'PLAN_10' and pnl >= 0.25:
        reason = 'TARGET_REACHED'
    elif plan == 'PLAN_12' and pnl >= 0.20:
        reason = 'COVERAGE_TP'
    elif plan == 'PLAN_05':
        if abs(cur - 0.5) - abs(entry - 0.5) > 0.05:
            reason = 'EXTENDS_AWAY'

    if reason:
        await bus.publish('TRADE_EXIT_REQUEST', {
            'asset': asset,
            'plan': plan,
            'direction': direction,
            'entry_price': entry,
            'exit_price': cur,
            'shares': shares,
            'bet_size': bet,
            'reason': reason,
            'pnl_pct': pnl,
            'market_id': state.get(f'position.{asset}.market_id', ''),
            'token_id': state.get(f'position.{asset}.token_id', ''),
        })


async def run_profit_taker() -> None:
    bus.subscribe('POLYMARKET_TICK', on_poly_tick)
    import asyncio
    while True:
        await asyncio.sleep(3600)
