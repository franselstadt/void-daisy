"""Polymarket CLOB websocket feed."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

import aiohttp
import ujson
import websockets

from core.event_bus import bus
from loguru import logger
from core.state import state

WS_URL = 'wss://ws-subscriptions-clob.polymarket.com/ws/market'
GAMMA = 'https://gamma-api.polymarket.com/markets'
CLOB = 'https://clob.polymarket.com'
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
                    async with sess.get(
                        GAMMA,
                        params={'active': 'true', 'closed': 'false', 'limit': 200},
                        timeout=aiohttp.ClientTimeout(total=10),
                    ) as r:
                        markets = await r.json(content_type=None)
                new_token_to_asset: dict[str, str] = {}
                new_token_to_market: dict[str, str] = {}
                new_active: dict[str, dict] = {}
                for m in markets:
                    q = str(m.get('question', '')).lower()
                    if not m.get('active', False):
                        continue
                    if '5' not in q or 'min' not in q:
                        continue
                    if not any(phrase in q for phrase in DIRECTION_PHRASES):
                        continue
                    mid = str(m.get('id', m.get('condition_id', '')))
                    ids = m.get('clobTokenIds', [])
                    if not isinstance(ids, list):
                        ids = [ids]
                    end_date = m.get('end_date_iso', m.get('end_date', ''))
                    for asset_name in ['BTC', 'ETH', 'SOL', 'XRP']:
                        if asset_name.lower() in q or {'btc': 'bitcoin', 'eth': 'ethereum', 'sol': 'solana', 'xrp': 'ripple'}.get(asset_name.lower(), '') in q:
                            for tid in ids:
                                tid = str(tid)
                                if tid:
                                    new_token_to_asset[tid] = asset_name
                                    new_token_to_market[tid] = mid
                            new_active[mid] = {'asset': asset_name, 'end_date': end_date, 'tokens': [str(i) for i in ids if i]}
                self.token_to_asset = new_token_to_asset
                self.token_to_market = new_token_to_market
                self.active_markets = new_active
            except Exception as exc:
                logger.warning(f'gamma_refresh_failed: {exc}')
            await asyncio.sleep(30)

    async def _subscribe(self, ws) -> None:  # type: ignore[no-untyped-def]
        ids = set(self.token_to_asset.keys())
        new = ids - self.subscribed
        if not new:
            return
        await ws.send(ujson.dumps({'assets_ids': list(new), 'type': 'Market'}))
        self.subscribed.update(new)

    def _secs_remaining(self, end_date: str | None) -> int:
        if not end_date:
            return 0
        try:
            end = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
            return max(0, int((end - datetime.now(timezone.utc)).total_seconds()))
        except Exception:
            return 0

    async def _fetch_orderbook(self, token_id: str) -> dict:
        try:
            async with aiohttp.ClientSession() as sess:
                async with sess.get(
                    f'{CLOB}/book',
                    params={'token_id': token_id},
                    timeout=aiohttp.ClientTimeout(total=2),
                ) as r:
                    book = await r.json(content_type=None)
            bids = book.get('bids', [])
            asks = book.get('asks', [])
            best_bid = float(bids[0]['price']) if bids else 0.5
            best_ask = float(asks[0]['price']) if asks else 0.5
            bid_depth = sum(float(b.get('size', 0)) for b in bids if abs(float(b.get('price', 0)) - best_bid) <= 0.05)
            ask_depth = sum(float(a.get('size', 0)) for a in asks if abs(float(a.get('price', 0)) - best_ask) <= 0.05)
            total = bid_depth + ask_depth
            imbalance = (bid_depth - ask_depth) / total if total > 0 else 0.0
            largest = max(
                [float(o.get('size', 0)) for o in bids + asks] or [0.0]
            )
            return {'bid_depth': bid_depth, 'ask_depth': ask_depth, 'order_imbalance': imbalance, 'largest_order': largest}
        except Exception:
            return {'bid_depth': 0, 'ask_depth': 0, 'order_imbalance': 0, 'largest_order': 0}

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
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=5)
                        except asyncio.TimeoutError:
                            continue
                        data = ujson.loads(raw)

                        token_id = str(data.get('asset_id', data.get('token_id', '')))
                        asset = self.token_to_asset.get(token_id)
                        if not asset:
                            raw_asset = str(data.get('asset', '')).upper()
                            if raw_asset in ('BTC', 'ETH', 'SOL', 'XRP'):
                                asset = raw_asset
                            else:
                                continue

                        market_id = self.token_to_market.get(token_id, str(data.get('market_id', '')))
                        end_date = self.active_markets.get(market_id, {}).get('end_date', data.get('end_date'))

                        yes = float(data.get('yes_price', data.get('price_yes', 0.0)) or 0.0)
                        no = float(data.get('no_price', data.get('price_no', 0.0)) or 0.0)
                        spread = abs(yes + no - 1.0)
                        v30 = float(state.get(f'price.{asset}.velocity_30s', 0.0))
                        expected = min(0.99, max(0.01, 0.50 + (v30 * 30 * 0.5)))
                        secs = self._secs_remaining(end_date)
                        elapsed = 300 - secs
                        lag = abs(expected - yes)

                        prev = self.prev.get(asset, {'yes_price': yes, 'no_price': no, 'spread': spread})
                        crash = max(abs(yes - prev.get('yes_price', yes)), abs(no - prev.get('no_price', no)))

                        ob: dict = {'bid_depth': 0, 'ask_depth': 0, 'order_imbalance': 0, 'largest_order': 0}
                        self._tick_counts[asset] = self._tick_counts.get(asset, 0) + 1
                        if self._tick_counts[asset] % 5 == 0 and token_id:
                            ob = await self._fetch_orderbook(token_id)

                        state.set_sync(f'polymarket.prev.{asset}', dict(prev))
                        self.prev[asset] = {'yes_price': yes, 'no_price': no, 'spread': spread}

                        await state.set(f'polymarket.{asset}.yes_price', yes)
                        await state.set(f'polymarket.{asset}.no_price', no)
                        await state.set(f'polymarket.{asset}.spread', spread)
                        await state.set(f'polymarket.{asset}.expected_yes', expected)
                        await state.set(f'polymarket.{asset}.lag_score', lag)
                        await state.set(f'polymarket.{asset}.seconds_remaining', secs)
                        await state.set(f'polymarket.{asset}.window_elapsed', elapsed)
                        await state.set(f'polymarket.{asset}.market_id', market_id)
                        await state.set(f'polymarket.{asset}.token_id', token_id)
                        await state.set(f'polymarket.{asset}.bid_depth', ob['bid_depth'])
                        await state.set(f'polymarket.{asset}.ask_depth', ob['ask_depth'])
                        await state.set(f'polymarket.{asset}.order_imbalance', ob['order_imbalance'])
                        await state.set(f'polymarket.{asset}.largest_order', ob['largest_order'])
                        await state.set(f'polymarket.{asset}.data_age_seconds', 0.0)
                        await state.set(f'polymarket.{asset}.timestamp', time.time())
                        await state.set('feed.polymarket.last_tick', time.time())

                        payload = {
                            'asset': asset,
                            'yes_price': yes,
                            'no_price': no,
                            'spread': spread,
                            'expected_yes': expected,
                            'lag_score': lag,
                            'seconds_remaining': secs,
                            'window_elapsed': elapsed,
                            'market_id': market_id,
                            'token_id': token_id,
                            'order_imbalance': ob['order_imbalance'],
                            'bid_depth': ob['bid_depth'],
                            'ask_depth': ob['ask_depth'],
                            'largest_order': ob['largest_order'],
                            'timestamp': time.time(),
                        }
                        await bus.publish('POLYMARKET_TICK', payload)
                        if crash > 0.15:
                            await bus.publish('PRICE_CRASH', {**payload, 'crash_magnitude': crash})
            except Exception as exc:
                await state.set('feed.polymarket.connected', False)
                logger.warning(f'polymarket_reconnect: {exc}, retry in {backoff}s')
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 5.0)
