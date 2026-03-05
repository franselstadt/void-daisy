"""Validates that the target market window is live/fresh before orders."""

from __future__ import annotations

import time

import aiohttp

from core.state import state

GAMMA = 'https://gamma-api.polymarket.com'


class WindowValidator:
    MIN_SECONDS_REMAINING = 45
    MAX_DATA_AGE_SECONDS = 3.0
    MIN_WINDOW_ELAPSED = 30
    MAX_OPPORTUNITY_AGE = 2.0
    MAX_SLIPPAGE_PCT = 0.15

    async def validate(self, opp: dict) -> tuple[bool, str]:
        asset = opp['asset']
        market_id = opp.get('market_id', '')
        direction = opp.get('direction', 'UP')
        entry = float(opp.get('entry_price', 0.0))

        if not state.get('feed.polymarket.connected', False):
            return False, 'POLYMARKET_FEED_DOWN'
        if not state.get(f'feed.binance.{asset}.connected', False):
            return False, f'BINANCE_FEED_DOWN_{asset}'

        ts = float(state.get(f'polymarket.{asset}.timestamp', 0.0))
        age = time.time() - ts
        if age > self.MAX_DATA_AGE_SECONDS:
            return False, f'STALE_DATA_{age:.1f}s'

        secs_left = int(state.get(f'polymarket.{asset}.seconds_remaining', 0))
        if secs_left < self.MIN_SECONDS_REMAINING:
            return False, f'WINDOW_CLOSING_{secs_left}s_left'

        elapsed = int(state.get(f'polymarket.{asset}.window_elapsed', 0))
        if elapsed < self.MIN_WINDOW_ELAPSED:
            return False, f'WINDOW_TOO_FRESH_{elapsed}s_elapsed'

        live_id = str(state.get(f'polymarket.{asset}.market_id', ''))
        if live_id and market_id and live_id != market_id:
            return False, 'STALE_MARKET_ID'

        opp_age = time.time() - float(opp.get('timestamp', time.time()))
        if opp_age > self.MAX_OPPORTUNITY_AGE and entry > 0:
            cur = float(state.get(f'polymarket.{asset}.yes_price', 0.0) if direction == 'UP' else state.get(f'polymarket.{asset}.no_price', 0.0))
            if cur > 0:
                slippage = abs(cur - entry) / entry
                if slippage > self.MAX_SLIPPAGE_PCT:
                    return False, f'PRICE_SLIPPED_{slippage:.1%}'

        if market_id:
            try:
                async with aiohttp.ClientSession() as sess:
                    async with sess.get(f'{GAMMA}/markets/{market_id}', timeout=aiohttp.ClientTimeout(total=1.5)) as r:
                        if r.status == 200:
                            m = await r.json()
                            if m.get('closed') or m.get('resolved'):
                                return False, 'MARKET_ALREADY_CLOSED'
                            if not m.get('active', True):
                                return False, 'MARKET_NOT_ACTIVE'
            except Exception:
                if secs_left < 60:
                    return False, 'CANNOT_VERIFY_MARKET_TOO_CLOSE_TO_EXPIRY'

        return True, 'OK'


validator = WindowValidator()
