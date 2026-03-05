"""Chainlink oracle monitor with lag detection."""

from __future__ import annotations

import asyncio
import time

import aiohttp

from core.event_bus import bus
from core.logger import logger
from core.state import state

PRIMARY_URLS = {
    'BTC': 'https://api.chain.link/v1/proxy/BTC-USD',
    'ETH': 'https://api.chain.link/v1/proxy/ETH-USD',
    'SOL': 'https://api.chain.link/v1/proxy/SOL-USD',
    'XRP': 'https://api.chain.link/v1/proxy/XRP-USD',
}
FALLBACK_URL = 'https://min-api.cryptocompare.com/data/price?fsym={asset}&tsyms=USD'


def _extract_price(payload: dict | list | None) -> float:
    if isinstance(payload, dict):
        for k in ('price', 'answer', 'value', 'USD'):
            if k in payload:
                try:
                    return float(payload[k])
                except Exception:
                    pass
    return 0.0


async def _fetch_price(sess: aiohttp.ClientSession, asset: str) -> tuple[float, float]:
    """Try primary Chainlink, fall back to CryptoCompare. Returns (price, update_ts)."""
    try:
        async with sess.get(PRIMARY_URLS[asset], timeout=aiohttp.ClientTimeout(total=5)) as r:
            payload = await r.json(content_type=None)
        oracle_price = _extract_price(payload)
        if oracle_price > 0:
            updated = float(payload.get('updated_at', payload.get('timestamp', time.time())) or time.time())
            if updated > 1e12:
                updated /= 1000
            return oracle_price, updated
    except Exception:
        pass

    try:
        async with sess.get(FALLBACK_URL.format(asset=asset), timeout=aiohttp.ClientTimeout(total=5)) as r:
            payload = await r.json(content_type=None)
        oracle_price = _extract_price(payload)
        if oracle_price > 0:
            return oracle_price, time.time()
    except Exception:
        pass

    return 0.0, 0.0


async def start_chainlink_feed() -> None:
    last_ts: dict[str, float] = {}
    async with aiohttp.ClientSession() as sess:
        while True:
            try:
                for asset in ['BTC', 'ETH', 'SOL', 'XRP']:
                    try:
                        oracle_price, updated = await _fetch_price(sess, asset)
                        spot = float(state.get(f'price.{asset}.price', 0.0))
                        if oracle_price <= 0 or spot <= 0:
                            await state.set(f'oracle.{asset}.lag_seconds', 0)
                            continue
                        lag = max(0.0, time.time() - updated)
                        delta = (spot - oracle_price) / oracle_price
                        direction = 'UP' if spot > oracle_price else 'DOWN' if spot < oracle_price else 'FLAT'

                        await state.set(f'oracle.{asset}.price', oracle_price)
                        await state.set(f'oracle.{asset}.lag_seconds', lag)
                        await state.set(f'oracle.{asset}.delta_pct', delta)
                        await state.set(f'oracle.{asset}.direction', direction)
                        await state.set(f'oracle.{asset}.last_update', updated)
                        await state.set('feed.chainlink.connected', True)

                        payload_evt = {
                            'asset': asset,
                            'oracle_price': oracle_price,
                            'binance_price': spot,
                            'lag_seconds': lag,
                            'delta_pct': delta,
                            'direction': direction,
                        }
                        await bus.publish('CHAINLINK_UPDATE', payload_evt)
                        if last_ts.get(asset) != updated:
                            last_ts[asset] = updated
                            await bus.publish('ORACLE_UPDATED', payload_evt)
                        if lag > 2.5 and abs(delta) > 0.003:
                            await bus.publish('ORACLE_LAG_DETECTED', payload_evt)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning('chainlink_asset_error', asset=asset, error=str(exc))
            except Exception as exc:  # noqa: BLE001
                await state.set('feed.chainlink.connected', False)
                logger.warning('chainlink_loop_error', error=str(exc))
            await asyncio.sleep(2)
