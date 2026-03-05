"""Order execution with maker-first and validation."""

from __future__ import annotations

import asyncio
import os
import random
import time
from dataclasses import dataclass

from core.config import config
from core.event_bus import bus
from core.logger import logger
from core.state import state
from trading import position_manager
from trading.window_validator import validator


@dataclass
class Result:
    success: bool
    fill_price: float = 0.0
    maker: bool = True
    order_id: str = ''
    error: str = ''


class Executor:
    def __init__(self) -> None:
        self.paper = os.getenv('PAPER_MODE', 'true').lower() == 'true'
        self.min_bet = float(os.getenv('MIN_BET', '1.0'))
        self._client = None
        if not self.paper:
            try:
                from py_clob_client.client import ClobClient
                key = os.getenv('POLYMARKET_PRIVATE_KEY', '')
                if key:
                    self._client = ClobClient(
                        host='https://clob.polymarket.com',
                        key=key,
                        chain_id=137,
                    )
            except Exception as exc:
                logger.warning('clob_client_init_failed', error=str(exc))

    async def _paper_fill(self, px: float) -> Result:
        await asyncio.sleep(0)
        return Result(True, max(0.01, px + random.uniform(-0.002, 0.002)), True, f'paper-{int(time.time() * 1000)}')

    def _rotate_proxy(self) -> None:
        host = os.getenv('PROXY_HOST', '')
        port = os.getenv('PROXY_PORT', '')
        user = os.getenv('PROXY_USER', '')
        pw = os.getenv('PROXY_PASS', '')
        if host and port:
            proxy_url = f'http://{user}:{pw}@{host}:{port}' if user else f'http://{host}:{port}'
            if self._client and hasattr(self._client, 'set_proxy'):
                self._client.set_proxy(proxy_url)
            logger.info('proxy_rotated', host=host)

    async def _live_fill(self, token_id: str, side: str, px: float, size: float) -> Result:
        if self._client is None:
            return Result(False, error='live_client_unavailable')
        maker_timeout = float(config.get('trading.maker_timeout_seconds', 3))
        max_retries = int(config.get('trading.max_proxy_retries', 10))

        for attempt in range(max_retries + 1):
            try:
                order_args = {
                    'token_id': token_id,
                    'price': px,
                    'size': size,
                    'side': side,
                }
                limit_resp = self._client.create_and_post_order(order_args)
                order_id = str(limit_resp.get('orderID', limit_resp.get('id', '')))

                filled = False
                deadline = time.time() + maker_timeout
                while time.time() < deadline:
                    await asyncio.sleep(0.25)
                    try:
                        status = self._client.get_order(order_id)
                        if status.get('status') in ('MATCHED', 'FILLED'):
                            filled = True
                            fill_px = float(status.get('price', px))
                            return Result(True, fill_px, True, order_id)
                    except Exception:
                        pass

                if not filled:
                    try:
                        self._client.cancel(order_id)
                    except Exception:
                        pass
                    market_args = {**order_args, 'order_type': 'FOK'}
                    market_resp = self._client.create_and_post_order(market_args)
                    market_id = str(market_resp.get('orderID', market_resp.get('id', '')))
                    return Result(True, px, False, market_id)

            except Exception as exc:
                err = str(exc).lower()
                if ('cloudflare' in err or '403' in err) and attempt < max_retries:
                    logger.warning('cloudflare_block_retrying', attempt=attempt + 1, max=max_retries)
                    await asyncio.sleep(0.5 * (attempt + 1))
                    self._rotate_proxy()
                    continue
                return Result(False, error=f'live_order_failed: {exc}')

        return Result(False, error='max_proxy_retries_exceeded')

    async def enter_trade(self, opp: dict) -> Result:
        ok, reason = await validator.validate(opp)
        if not ok:
            await bus.publish('TRADE_BLOCKED', {'asset': opp.get('asset'), 'reason': reason, 'plan': opp.get('plan')})
            return Result(False, error=reason)

        bet = max(self.min_bet, float(opp.get('bet_size', 1.0)))
        entry_px = float(opp.get('entry_price', 0.5))
        if self.paper:
            r = await self._paper_fill(entry_px)
        else:
            token_id = str(opp.get('token_id', ''))
            side = 'BUY'
            size = round(bet / max(entry_px, 1e-9), 6)
            r = await self._live_fill(token_id, side, entry_px, size)

        if not r.success:
            await bus.publish('ORDER_FAILED', {'stage': 'entry', 'asset': opp.get('asset'), 'error': r.error})
            return r

        shares = round(bet / max(r.fill_price, 1e-9), 6)
        trade = {
            **opp,
            'entry_price': r.fill_price,
            'bet_size': bet,
            'shares': shares,
            'maker_fill': 1 if r.maker else 0,
            'paper': 1 if self.paper else 0,
        }
        position_manager.open_position(trade)
        state.set_sync(f'coverage.last_attempt.{opp["asset"]}', time.time())
        await bus.publish('TRADE_ENTERED', trade)
        return r

    async def exit_trade(self, req: dict) -> Result:
        exit_px = float(req.get('exit_price', 0.5))
        if self.paper:
            r = await self._paper_fill(exit_px)
        else:
            token_id = str(req.get('token_id', ''))
            side = 'SELL'
            shares = float(req.get('shares', 0.0))
            r = await self._live_fill(token_id, side, exit_px, shares)

        if not r.success:
            await bus.publish('ORDER_FAILED', {'stage': 'exit', 'asset': req.get('asset'), 'error': r.error})
            return r

        asset = req['asset']
        shares = float(req.get('shares', 0.0))
        bet = float(req.get('bet_size', 0.0))
        gross = shares * r.fill_price - bet
        fee = 0.0 if r.maker else bet * 0.02
        net = gross - fee
        won = 1 if net > 0 else 0

        position_manager.close_position(asset)
        bankroll = float(state.get('stats.bankroll', state.get('bankroll', 0.0))) + net
        state.set_sync('stats.bankroll', bankroll)
        state.set_sync('bankroll', bankroll)
        state.set_sync('stats.pnl_session', float(state.get('stats.pnl_session', 0.0)) + net)
        state.set_sync('stats.pnl_this_hour', float(state.get('stats.pnl_this_hour', 0.0)) + net)
        state.set_sync('stats.trades_this_session', int(state.get('stats.trades_this_session', 0)) + 1)

        last10 = list(state.get('stats._last10', []))
        last20 = list(state.get('stats._last20', []))
        last10.append(won)
        last20.append(won)
        last10 = last10[-10:]
        last20 = last20[-20:]
        state.set_sync('stats._last10', last10)
        state.set_sync('stats._last20', last20)
        state.set_sync('stats.win_rate_10', sum(last10) / len(last10) if last10 else 0.5)
        state.set_sync('stats.win_rate_20', sum(last20) / len(last20) if last20 else 0.5)

        losses = int(state.get('stats.consecutive_losses', 0))
        wins = int(state.get('stats.consecutive_wins', 0))
        state.set_sync('stats.consecutive_losses', losses + 1 if won == 0 else 0)
        state.set_sync('stats.consecutive_wins', wins + 1 if won == 1 else 0)

        exit_evt = {
            **req,
            'exit_price': r.fill_price,
            'gross_pnl': gross,
            'net_pnl': net,
            'pnl_pct': net / max(bet, 1e-9),
            'won': won,
            'maker_fill': 1 if r.maker else 0,
            'paper': 1 if self.paper else 0,
            'timestamp': time.time(),
        }
        await bus.publish('TRADE_EXITED', exit_evt)
        return r


executor = Executor()
