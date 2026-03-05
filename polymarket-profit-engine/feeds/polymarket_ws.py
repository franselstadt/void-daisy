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
CLOB_BOOK = 'https://clob.polymarket.com/book'

DIRECTION_PHRASES = ('up or down', 'higher or lower', 'above or below')


class PolymarketFeed:
    def __init__(self) -> None:
        self.active_markets: dict[str, dict] = {}
        self.token_to_asset: dict[str, str] = {}
        self.token_to_market: dict[str, str] = {}
        self.subscribed: set[str] = set()
        self.prev: dict[str, dict] = {}
        self._tick_counts: dict[str, int] = {}

    async def _refresh_markets(self) -> None:
        while True:
            try:
                async with aiohttp.ClientSession() as sess:
                    params = {'active': 'true', 'closed': 'false', 'limit': 200}
                    async with sess.get(GAMMA, params=params, timeout=aiohttp.ClientTimeout(total=10)) as r:
                        markets = await r.json(content_type=None)
                new_active: dict[str, dict] = {}
                new_t2a: dict[str, str] = {}
                new_t2m: dict[str, str] = {}
                for m in markets:
                    q = str(m.get('question', '')).lower()
                    if not m.get('active', False):
                        continue
                    if '5' not in q or 'min' not in q:
                        continue
                    if not any(phrase in q for phrase in DIRECTION_PHRASES):
                        continue
                    ids = m.get('clobTokenIds', [])
                    if not isinstance(ids, list):
                        ids = [ids]
                    mid = str(m.get('id', m.get('condition_id', '')))
                    for asset in ('BTC', 'ETH', 'SOL', 'XRP'):
                        if asset.lower() in q:
                            token_ids = [str(i) for i in ids if i]
                            new_active[mid] = m
                            for tid in token_ids:
                                new_t2a[tid] = asset
                                new_t2m[tid] = mid
                self.active_markets = new_active
                self.token_to_asset = new_t2a
                self.token_to_market = new_t2m
            except Exception as exc:  # noqa: BLE001
                logger.warning('gamma_refresh_failed', error=str(exc))
            await asyncio.sleep(30)

    async def _subscribe(self, ws) -> None:  # type: ignore[no-untyped-def]
        ids = set(self.token_to_asset.keys())
        new = ids - self.subscribed
        if not new:
            return
        await ws.send(json.dumps({'assets_ids': list(new), 'type': 'Market'}))
        self.subscribed.update(new)

    def _secs_remaining(self, end_date: str | None) -> int:
        if not end_date:
            return 0
        try:
            end = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
            return max(0, int((end - datetime.now(timezone.utc)).total_seconds()))
        except Exception:
            return 0

    async def _fetch_orderbook(self, sess: aiohttp.ClientSession, token_id: str) -> dict:
        try:
            async with sess.get(CLOB_BOOK, params={'token_id': token_id},
                                timeout=aiohttp.ClientTimeout(total=3)) as r:
                book = await r.json(content_type=None)
            bids = book.get('bids', [])
            asks = book.get('asks', [])
            bid_depth = sum(float(b.get('size', 0)) for b in bids)
            ask_depth = sum(float(a.get('size', 0)) for a in asks)
            total = bid_depth + ask_depth
            imbalance = (bid_depth - ask_depth) / total if total else 0.0
            all_sizes = [float(o.get('size', 0)) for o in bids + asks]
            largest = max(all_sizes) if all_sizes else 0.0
            return {
                'bid_depth': bid_depth,
                'ask_depth': ask_depth,
                'order_imbalance': imbalance,
                'largest_order': largest,
            }
        except Exception:
            return {'bid_depth': 0.0, 'ask_depth': 0.0, 'order_imbalance': 0.0, 'largest_order': 0.0}

    async def run(self) -> None:
        asyncio.create_task(self._refresh_markets())
        backoff = 0.2
        while True:
            try:
                async with websockets.connect(WS_URL, ping_interval=20, ping_timeout=20) as ws:
                    await state.set('feed.polymarket.connected', True)
                    await state.set('feed.polymarket.last_tick', time.time())
                    backoff = 0.2
                    sess = aiohttp.ClientSession()
                    try:
                        while True:
                            await self._subscribe(ws)
                            try:
                                raw = await asyncio.wait_for(ws.recv(), timeout=5)
                            except asyncio.TimeoutError:
                                continue
                            data = json.loads(raw)
                            token_id = str(data.get('asset_id', data.get('token_id', '')))
                            asset = self.token_to_asset.get(token_id, str(data.get('asset', '')).upper())
                            if asset not in ('BTC', 'ETH', 'SOL', 'XRP'):
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

                            prev = self.prev.get(asset, {'yes': yes, 'no': no})
                            change = yes - prev['yes']
                            crash = max(abs(yes - prev['yes']), abs(no - prev['no']))
                            self.prev[asset] = {'yes': yes, 'no': no}

                            self._tick_counts[asset] = self._tick_counts.get(asset, 0) + 1
                            ob = {'bid_depth': 0.0, 'ask_depth': 0.0, 'order_imbalance': 0.0, 'largest_order': 0.0}
                            if self._tick_counts[asset] % 5 == 0 and token_id:
                                ob = await self._fetch_orderbook(sess, token_id)

                            await state.set(f'polymarket.{asset}.yes_price', yes)
                            await state.set(f'polymarket.{asset}.no_price', no)
                            await state.set(f'polymarket.{asset}.spread', spread)
                            await state.set(f'polymarket.{asset}.expected_yes', expected)
                            await state.set(f'polymarket.{asset}.lag_score', lag)
                            await state.set(f'polymarket.{asset}.seconds_remaining', secs)
                            await state.set(f'polymarket.{asset}.window_elapsed', elapsed)
                            await state.set(f'polymarket.{asset}.market_id', self.token_to_market.get(token_id, ''))
                            await state.set(f'polymarket.{asset}.token_id', token_id)
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
                                'market_id': self.token_to_market.get(token_id, ''),
                                'token_id': token_id,
                                'bid_depth': ob['bid_depth'],
                                'ask_depth': ob['ask_depth'],
                                'order_imbalance': ob['order_imbalance'],
                                'largest_order': ob['largest_order'],
                                'timestamp': time.time(),
                            }
                            await bus.publish('POLYMARKET_TICK', payload)
                            if crash > 0.15:
                                await bus.publish('PRICE_CRASH', {**payload, 'crash_magnitude': crash})
                    finally:
                        await sess.close()
            except Exception as exc:  # noqa: BLE001
                await state.set('feed.polymarket.connected', False)
                await bus.publish('FEED_DISCONNECTED', {'feed': 'polymarket', 'error': str(exc)})
                logger.warning('polymarket_reconnect', sleep=backoff, error=str(exc))
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 5.0)
