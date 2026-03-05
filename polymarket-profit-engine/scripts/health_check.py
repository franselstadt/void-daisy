"""OpenClaw health check executed every 60 seconds."""

from __future__ import annotations

import sys
import time

from core.state import state


def main() -> int:
    now = time.time()
    bankroll = float(state.get('stats.bankroll', state.get('bankroll', 0.0)))
    if bankroll <= 0:
        return 2
    if not state.get('feed.polymarket.connected', False):
        return 3
    for a in ['BTC', 'ETH', 'SOL', 'XRP']:
        if not state.get(f'feed.binance.{a}.connected', False):
            return 4
        ts = float(state.get(f'price.{a}.timestamp', 0.0))
        if ts > 0 and now - ts > 20:
            return 5
    return 0


if __name__ == '__main__':
    sys.exit(main())
