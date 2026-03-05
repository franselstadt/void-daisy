"""Polymarket CLOB websocket feed."""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone

import aiohttp
import websockets

from core.event_bus import bus
from core.logger import logger
from core.state import state

WS_URL = 'wss://ws-subscriptions-clob.polymarket.com/ws/market'
GAMMA = 'https://gamma-api.polymarket.com/markets'


class PolymarketFeed:
    def __init__(self) -> None:
        self.market_map: dict[str, list[str]] = {'BTC': [], 'ETH': [], 'SOL': [], 'XRP': []}
        self.subscribed: set[str] = set()
        self.prev: dict[str, tuple[float, float]] = {}

    async def _refresh_markets(self) -> None:
        while True:
            try:
                async with aiohttp.ClientSession() as sess:
                    async with sess.get(GAMMA, timeout=10) as r:
                        markets = await r.json(content_type=None)
                nxt = {'BTC': [], 'ETH': [], 'SOL': [], 'XRP': []}
                for m in markets:
                    q = str(m.get('question', '')).lower()
                    if not m.get('active', False):
                        continue
                    if '5' not in q or 'min' not in q:
                        continue
                    ids = m.get('clobTokenIds', [])
                    if not isinstance(ids, list):
                        ids = [ids]
                    for asset in nxt:
                        if asset.lower() in q:
                            nxt[asset].extend([str(i) for i in ids if i])
                self.market_map = nxt
            except Exception as exc:  # noqa: BLE001
                logger.warning('gamma_refresh_failed', error=str(exc))
            await asyncio.sleep(30)

    async def _subscribe(self, ws) -> None:  # type: ignore[no-untyped-def]
        ids = {i for arr in self.market_map.values() for i in arr}
        new = ids - self.subscribed
        if not new:
            return
        await ws.send(json.dumps({'type': 'subscribe', 'channel': 'market', 'assets_ids': list(new)}))
        self.subscribed.update(new)

    def _secs_remaining(self, end_date: str | None) -> int:
        if not end_date:
            return 0
        try:
            end = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
            return max(0, int((end - datetime.now(timezone.utc)).total_seconds()))
        except Exception:
            return 0

    async def run(self) -> None:
        asyncio.create_task(self._refresh_markets())
        backoff = 0.2
        while True:
            try:
                async with websockets.connect(WS_URL, ping_interval=20, ping_timeout=20) as ws:
                    await state.set('feed.polymarket.connected', True)
                    await state.set('feed.polymarket.last_tick', time.time())
                    backoff = 0.2
                    while True:
                        await self._subscribe(ws)
                        raw = await asyncio.wait_for(ws.recv(), timeout=1)
                        data = json.loads(raw)
                        asset = str(data.get('asset', '')).upper()
                        if asset not in self.market_map:
                            continue
                        yes = float(data.get('yes_price', data.get('price_yes', 0.0)) or 0.0)
                        no = float(data.get('no_price', data.get('price_no', 0.0)) or 0.0)
                        spread = abs(yes + no - 1.0)
                        v30 = float(state.get(f'price.{asset}.velocity_30s', 0.0))
                        sensitivity = 30.0
                        expected = min(0.99, max(0.01, 0.50 + (v30 * 30 * sensitivity)))
                        secs = self._secs_remaining(data.get('end_date'))
                        elapsed = 300 - secs
                        lag = abs(expected - yes)
                        prev = self.prev.get(asset, (yes, no))
                        change = yes - prev[0]
                        crash = max(abs(yes - prev[0]), abs(no - prev[1]))
                        self.prev[asset] = (yes, no)

                        await state.set(f'polymarket.{asset}.yes_price', yes)
                        await state.set(f'polymarket.{asset}.no_price', no)
                        await state.set(f'polymarket.{asset}.spread', spread)
                        await state.set(f'polymarket.{asset}.expected_yes', expected)
                        await state.set(f'polymarket.{asset}.lag_score', lag)
                        await state.set(f'polymarket.{asset}.seconds_remaining', secs)
                        await state.set(f'polymarket.{asset}.window_elapsed', elapsed)
                        await state.set(f'polymarket.{asset}.market_id', str(data.get('market_id', '')))
                        await state.set(f'polymarket.{asset}.token_id', str(data.get('token_id', '')))
                        await state.set(f'polymarket.{asset}.timestamp', time.time())
                        await state.set(f'feed.polymarket.last_tick', time.time())

                        payload = {
                            'asset': asset,
                            'yes_price': yes,
                            'no_price': no,
                            'spread': spread,
                            'expected_yes': expected,
                            'lag_score': lag,
                            'price_change_since_last_tick': change,
                            'seconds_remaining': secs,
                            'window_elapsed': elapsed,
                            'market_id': str(data.get('market_id', '')),
                            'token_id': str(data.get('token_id', '')),
                            'orderbook': data.get('orderbook', {}),
                            'timestamp': time.time(),
                        }
                        await bus.publish('POLYMARKET_TICK', payload)
                        if crash > 0.15:
                            await bus.publish('PRICE_CRASH', {**payload, 'crash_magnitude': crash})
            except asyncio.TimeoutError:
                continue
            except Exception as exc:  # noqa: BLE001
                await state.set('feed.polymarket.connected', False)
                await bus.publish('FEED_DISCONNECTED', {'feed': 'polymarket', 'error': str(exc)})
                logger.warning('polymarket_reconnect', sleep=backoff, error=str(exc))
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 5.0)
