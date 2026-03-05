"""Order execution with maker-first and validation."""

from __future__ import annotations

import asyncio
import os
import random
import time
from dataclasses import dataclass

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

    async def _live_fill(self, px: float) -> Result:
        if self._client is None:
            return Result(False, error='live_client_unavailable')
        logger.info('live_order_placeholder', price=px)
        await asyncio.sleep(0.05)
        return Result(True, px, True, f'live-{int(time.time() * 1000)}')

    async def enter_trade(self, opp: dict) -> Result:
        ok, reason = await validator.validate(opp)
        if not ok:
            await bus.publish('TRADE_BLOCKED', {'asset': opp.get('asset'), 'reason': reason, 'plan': opp.get('plan')})
            return Result(False, error=reason)

        bet = max(self.min_bet, float(opp.get('bet_size', 1.0)))
        if self.paper:
            r = await self._paper_fill(float(opp.get('entry_price', 0.5)))
        else:
            r = await self._live_fill(float(opp.get('entry_price', 0.5)))

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
        if self.paper:
            r = await self._paper_fill(float(req.get('exit_price', 0.5)))
        else:
            r = await self._live_fill(float(req.get('exit_price', 0.5)))

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
