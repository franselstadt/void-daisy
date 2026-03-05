"""Chainlink oracle monitor with lag detection."""

from __future__ import annotations

import asyncio
import time

import aiohttp

from core.event_bus import bus
from core.logger import logger
from core.state import state

URLS = {
    'BTC': 'https://data.chain.link/streams/btc-usd',
    'ETH': 'https://data.chain.link/streams/eth-usd',
    'SOL': 'https://data.chain.link/streams/sol-usd',
    'XRP': 'https://data.chain.link/streams/xrp-usd',
}


def _extract_price(payload) -> float:  # type: ignore[no-untyped-def]
    if isinstance(payload, dict):
        for k in ('price', 'answer', 'value'):
            if k in payload:
                try:
                    return float(payload[k])
                except Exception:
                    pass
    return 0.0


async def start_chainlink_feed() -> None:
    last_ts: dict[str, float] = {}
    async with aiohttp.ClientSession() as sess:
        while True:
            try:
                for asset, url in URLS.items():
                    try:
                        async with sess.get(url, timeout=8) as r:
                            payload = await r.json(content_type=None)
                        oracle_price = _extract_price(payload)
                        spot = float(state.get(f'price.{asset}.price', 0.0))
                        if oracle_price <= 0 or spot <= 0:
                            continue
                        updated = float(payload.get('updated_at', payload.get('timestamp', time.time())) or time.time())
                        if updated > 1e12:
                            updated /= 1000
                        lag = max(0.0, time.time() - updated)
                        delta = (oracle_price - spot) / spot
                        direction = 'UP' if oracle_price > spot else 'DOWN' if oracle_price < spot else 'FLAT'

                        await state.set(f'oracle.{asset}.price', oracle_price)
                        await state.set(f'oracle.{asset}.lag_seconds', lag)
                        await state.set(f'oracle.{asset}.delta_pct', delta)
                        await state.set(f'oracle.{asset}.direction', direction)
                        await state.set(f'oracle.{asset}.last_update', updated)
                        await state.set('feed.chainlink.connected', True)

                        payload_evt = {'asset': asset, 'oracle_price': oracle_price, 'binance_price': spot, 'lag_seconds': lag, 'delta_pct': delta, 'direction': direction}
                        await bus.publish('CHAINLINK_UPDATE', payload_evt)
                        if last_ts.get(asset) != updated:
                            last_ts[asset] = updated
                            await bus.publish('ORACLE_UPDATED', payload_evt)
                        if lag > 2.0 and abs(delta) > 0.003:
                            await bus.publish('ORACLE_LAG_DETECTED', payload_evt)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning('chainlink_asset_error', asset=asset, error=str(exc))
            except Exception as exc:  # noqa: BLE001
                await state.set('feed.chainlink.connected', False)
                logger.warning('chainlink_loop_error', error=str(exc))
            await asyncio.sleep(2)
