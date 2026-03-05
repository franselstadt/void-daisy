"""Auto profit-taker checks all open positions every polymarket tick."""

from __future__ import annotations

import time

from core.event_bus import bus
from core.state import state

EXIT_LOGIC: dict[str, dict] = {
    'PLAN_01': {
        'stop_price': 0.02,
        'breakeven_pct': 0.33,
        'levels': [(0.33, 3), (0.50, 4), (0.70, 5)],
        'max_pct': 0.85,
        'max_hold_secs': None,
        'trailing_after_pct': None,
        'trailing_distance': None,
        'reversal_exit': True,
    },
    'PLAN_02': {
        'stop_price': None,
        'exit_trigger': 'oracle_updated',
        'max_pct': 0.30,
        'max_hold_secs': 20,
        'reversal_exit': True,
    },
    'PLAN_03': {
        'stop_price': None,
        'exit_trigger': 'lag_resolved',
        'max_pct': 0.30,
        'max_hold_secs': None,
        'reversal_exit': True,
    },
    'PLAN_04': {
        'stop_price': None,
        'trailing_after_pct': 0.20,
        'trailing_distance': 0.12,
        'max_pct': 0.75,
        'max_hold_secs': None,
        'reversal_exit': True,
        'volume_exit': True,
    },
    'PLAN_05': {
        'stop_price': None,
        'extend_stop_pct': -0.05,
        'breakeven_pct': 0.15,
        'trailing_after_pct': 0.15,
        'trailing_distance': 0.10,
        'max_pct': 0.25,
        'max_hold_secs': None,
        'reversal_exit': True,
    },
    'PLAN_06': {'max_pct': 0.25, 'stop_price': 0.02, 'reversal_exit': True},
    'PLAN_07': {'max_pct': 0.35, 'stop_price': 0.02, 'reversal_exit': True},
    'PLAN_08': {'max_pct': 0.25, 'stop_price': 0.02, 'reversal_exit': True},
    'PLAN_09': {'max_pct': 0.40, 'stop_price': 0.02, 'reversal_exit': True, 'max_hold_secs': 120},
    'PLAN_10': {'max_pct': 0.50, 'stop_price': 0.02, 'reversal_exit': True},
    'PLAN_11': {'max_pct': 0.20, 'stop_price': 0.02, 'exit_trigger': 'spread_normalised'},
    'PLAN_12': {'stop_price': 0.02, 'breakeven_pct': 0.33, 'levels': [(0.33, 3), (0.50, 4)], 'max_pct': 0.70},
}


def _count_green(direction: str, asset: str, tick: dict, secs_left: int) -> int:
    g = 0
    v10 = float(state.get(f'price.{asset}.velocity_10s', 0.0))
    v30 = float(state.get(f'price.{asset}.velocity_30s', 0.0))
    vol = float(state.get(f'price.{asset}.volume_ratio_10_60', 1.0))
    imb = float(tick.get('order_imbalance', state.get(f'polymarket.{asset}.order_imbalance', 0.0)))
    if direction == 'UP':
        if v10 > 0:
            g += 1
        if v10 > v30:
            g += 1
        if imb > 0.1:
            g += 1
    else:
        if v10 < 0:
            g += 1
        if v10 < v30:
            g += 1
        if imb < -0.1:
            g += 1
    if vol >= 0.8:
        g += 1
    if secs_left > 90:
        g += 1
    return g


async def on_poly_tick(event: dict) -> None:
    asset = event['asset']
    if not state.get(f'position.open.{asset}', False):
        return

    plan = str(state.get(f'position.{asset}.plan', 'PLAN_01'))
    direction = str(state.get(f'position.{asset}.direction', 'UP'))
    entry = float(state.get(f'position.{asset}.entry_price', 0.0))
    entry_time = float(state.get(f'position.{asset}.entry_time', 0.0))
    shares = float(state.get(f'position.{asset}.shares', 0.0))
    bet = float(state.get(f'position.{asset}.bet_size', 0.0))
    stop_moved = bool(state.get(f'position.{asset}.stop_moved_to_entry', False))
    high_wm = float(state.get(f'position.{asset}.high_watermark_price', entry))

    cur = float(event['yes_price'] if direction == 'UP' else event['no_price'])
    secs = int(event.get('seconds_remaining', 0))
    pnl = ((shares * cur) - bet) / max(bet, 1e-9)
    hold_secs = time.time() - entry_time

    logic = EXIT_LOGIC.get(plan, EXIT_LOGIC['PLAN_01'])

    if cur > high_wm:
        state.set_sync(f'position.{asset}.high_watermark_price', cur)
        high_wm = cur

    reason = None

    stop_p = logic.get('stop_price')
    if stop_p and cur <= stop_p:
        reason = 'STOP_LOSS'

    elif secs <= 30:
        reason = 'WINDOW_EXPIRING'

    elif secs <= 60 and pnl > 0:
        reason = 'TIME_PROFIT_LOCK'

    elif plan == 'PLAN_02':
        oracle_lag = float(state.get(f'oracle.{asset}.lag_seconds', 99))
        if oracle_lag < 1.0 or hold_secs > (logic.get('max_hold_secs') or 20):
            reason = 'ORACLE_RESOLVED'

    elif plan == 'PLAN_03':
        lag_score = float(event.get('lag_score', state.get(f'polymarket.{asset}.lag_score', 0.0)))
        if lag_score < 0.02:
            reason = 'LAG_RESOLVED'
        btc_dir = float(state.get('price.BTC.velocity_30s', 0.0))
        if asset != 'BTC' and ((direction == 'UP' and btc_dir < 0) or (direction == 'DOWN' and btc_dir > 0)):
            reason = 'BTC_REVERSED'

    elif plan == 'PLAN_11':
        if float(event.get('spread', state.get(f'polymarket.{asset}.spread', 0.1))) <= 0.03:
            reason = 'SPREAD_NORMALISED'

    if not reason and pnl >= logic.get('max_pct', 0.85):
        reason = 'MAX_TARGET_HIT'

    max_secs = logic.get('max_hold_secs')
    if not reason and max_secs and hold_secs > max_secs:
        reason = 'MAX_HOLD_TIME'

    if not reason and stop_moved:
        if cur <= entry:
            reason = 'BREAKEVEN_STOP'

    trail_after = logic.get('trailing_after_pct')
    trail_dist = logic.get('trailing_distance')
    if not reason and trail_after and trail_dist:
        if pnl >= trail_after:
            trail_stop = high_wm * (1 - trail_dist)
            if cur < trail_stop:
                reason = 'TRAILING_STOP'

    if not reason and 'levels' in logic:
        for level_pct, green_needed in logic['levels']:
            if pnl >= level_pct:
                if not stop_moved:
                    state.set_sync(f'position.{asset}.stop_moved_to_entry', True)
                green = _count_green(direction, asset, event, secs)
                if green < green_needed:
                    reason = f'PROFIT_{int(level_pct * 100)}PCT'
                break

    if not reason and logic.get('reversal_exit') and pnl > 0:
        v10 = float(state.get(f'price.{asset}.velocity_10s', 0.0))
        if direction == 'UP' and v10 < -0.002:
            reason = 'MOMENTUM_REVERSED'
        elif direction == 'DOWN' and v10 > 0.002:
            reason = 'MOMENTUM_REVERSED'

    if not reason and logic.get('volume_exit'):
        vol_r = float(state.get(f'price.{asset}.volume_ratio_10_60', 1.0))
        if vol_r < 0.5:
            reason = 'VOLUME_COLLAPSED'

    extend_stop = logic.get('extend_stop_pct')
    if not reason and extend_stop:
        yes = float(event.get('yes_price', 0.5))
        mid_distance = abs(yes - 0.5)
        if mid_distance > 0.35:
            reason = 'MEAN_REVERT_FAILED'

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
