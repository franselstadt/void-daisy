"""Telegram command and alert interface."""

from __future__ import annotations

import asyncio
import os
import time

import aiosqlite
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from core.event_bus import bus
from core.state import state


class TelegramReporter:
    def __init__(self, db_path: str = 'data/trades.db') -> None:
        self.db_path = db_path
        self.chat_id = os.getenv('TELEGRAM_CHAT_ID', '')
        token = os.getenv('TELEGRAM_BOT_TOKEN', '')
        self.enabled = bool(token and self.chat_id)
        self.app = Application.builder().token(token).build() if self.enabled else None

    async def send(self, text: str) -> None:
        if not self.enabled or not self.app:
            return
        await self.app.bot.send_message(chat_id=self.chat_id, text=text)

    async def cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        now = time.time()
        tags = []
        for a in ['BTC', 'ETH', 'SOL', 'XRP']:
            last = float(state.get(f'coverage.last_attempt.{a}', 0.0))
            gap = (now - last) / 60 if last > 0 else 999
            tags.append(f"{a} ✅" if gap <= 6 else f"{a} ⚠️({gap:.1f}m)")
        msg = (
            f"Mode: {state.get('bot.degradation_level', 0)}\n"
            f"Regime: {state.get('bot.current_regime', 'RANGING')}\n"
            f"Bankroll: ${float(state.get('stats.bankroll', state.get('bankroll', 0.0))):.2f}\n"
            f"Open positions: {len(state.get('positions.open', []))}\n"
            f"Coverage: {' | '.join(tags)}"
        )
        await update.message.reply_text(msg)

    async def cmd_bankroll(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        b = float(state.get('stats.bankroll', state.get('bankroll', 0.0)))
        pnl = float(state.get('stats.pnl_session', 0.0))
        await update.message.reply_text(f"Bankroll ${b:.2f} | Session PnL ${pnl:+.2f}")

    async def cmd_plans(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.message.reply_text('Plans active: PLAN_01..PLAN_12 (regime/degradation gated).')

    async def cmd_positions(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        positions = state.get('positions.open', [])
        if not positions:
            await update.message.reply_text('No open positions.')
            return
        lines = []
        for a in positions:
            lines.append(f"{a} {state.get(f'position.{a}.plan')} {state.get(f'position.{a}.direction')} @ {float(state.get(f'position.{a}.entry_price',0.0)):.3f}")
        await update.message.reply_text('\n'.join(lines))

    async def cmd_trades(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            rows = await (await db.execute('SELECT asset, strategy, direction, pnl_pct, exit_reason FROM trades ORDER BY id DESC LIMIT 10')).fetchall()
        if not rows:
            await update.message.reply_text('No trades yet.')
            return
        lines = [f"{r['asset']} {r['strategy']} {r['direction']} {float(r['pnl_pct']):+.1%} ({r['exit_reason']})" for r in rows]
        await update.message.reply_text('\n'.join(lines))

    async def cmd_performance(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        wr10 = float(state.get('stats.win_rate_10', 0.5))
        wr20 = float(state.get('stats.win_rate_20', 0.5))
        await update.message.reply_text(f"WinRate10: {wr10:.1%} | WinRate20: {wr20:.1%}")

    async def cmd_regime(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.message.reply_text(str({
            'regime': state.get('bot.current_regime', 'RANGING'),
            'trend_score': state.get('regime.trend_score', 0.5),
            'volatility_ratio': state.get('regime.volatility_ratio', 1.0),
            'corr': state.get('regime.avg_correlation', 0.8),
        }))

    async def cmd_coverage(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        lines = []
        for a in ['BTC', 'ETH', 'SOL', 'XRP']:
            c = int(state.get(f'coverage.window_covered.{a}', 0))
            t = int(state.get(f'coverage.window_total.{a}', 0))
            pct = (c / t * 100) if t else 0.0
            lines.append(f"{a}: {pct:.0f}% ({c}/{t})")
        await update.message.reply_text('Coverage\n' + '\n'.join(lines))

    async def cmd_pause(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        state.set_sync('bot.paused', True)
        await update.message.reply_text('Paused.')

    async def cmd_resume(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        state.set_sync('bot.paused', False)
        state.set_sync('bot.hard_stopped', False)
        await update.message.reply_text('Resumed.')

    async def cmd_emergency(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        state.set_sync('bot.emergency_stopped', True)
        await update.message.reply_text('Emergency stop active.')

    async def on_stoploss(self, event: dict) -> None:
        await self.send(f"STOP LOSS {event.get('asset')} {float(event.get('pnl_pct',0.0)):.1%}")

    async def on_coverage_alert(self, event: dict) -> None:
        await self.send(f"⚠️ Coverage alert {event.get('asset')} gap {float(event.get('gap_minutes',0.0)):.1f}m")

    async def on_coverage_failure(self, event: dict) -> None:
        await self.send(f"🚨 Coverage failure {event.get('asset')} reasons={event.get('reasons')}")

    async def on_regime_changed(self, event: dict) -> None:
        await self.send(f"Regime changed: {event.get('old')} -> {event.get('new')}")

    async def run(self) -> None:
        bus.subscribe('STOP_LOSS_HIT', self.on_stoploss)
        bus.subscribe('COVERAGE_ALERT', self.on_coverage_alert)
        bus.subscribe('COVERAGE_FAILURE', self.on_coverage_failure)
        bus.subscribe('REGIME_CHANGED', self.on_regime_changed)
        if not self.enabled or not self.app:
            while True:
                await asyncio.sleep(3600)

        handlers = [
            ('status', self.cmd_status), ('bankroll', self.cmd_bankroll), ('plans', self.cmd_plans), ('positions', self.cmd_positions),
            ('trades', self.cmd_trades), ('performance', self.cmd_performance), ('regime', self.cmd_regime), ('coverage', self.cmd_coverage),
            ('pause', self.cmd_pause), ('resume', self.cmd_resume), ('emergency_stop', self.cmd_emergency),
        ]
        for name, fn in handlers:
            self.app.add_handler(CommandHandler(name, fn))

        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling()
        try:
            while True:
                await asyncio.sleep(3600)
        finally:
            await self.app.updater.stop()
            await self.app.stop()
            await self.app.shutdown()
