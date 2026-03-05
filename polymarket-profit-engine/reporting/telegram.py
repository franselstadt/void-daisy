"""Telegram command and alert interface with user authentication."""

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

    def _authorized(self, update: Update) -> bool:
        if not self.chat_id:
            return True
        return str(update.effective_chat.id) == self.chat_id

    async def send(self, text: str) -> None:
        if not self.enabled or not self.app:
            return
        try:
            await self.app.bot.send_message(chat_id=self.chat_id, text=text)
        except Exception:
            pass

    async def cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._authorized(update):
            return
        now = time.time()
        tags = []
        for a in ['BTC', 'ETH', 'SOL', 'XRP']:
            last = float(state.get(f'coverage.last_attempt.{a}', 0.0))
            gap = (now - last) / 60 if last > 0 else 999
            tags.append(f"{a} ✅" if gap <= 6 else f"{a} ⚠️({gap:.1f}m)")
        paper = "PAPER" if state.get('bot.paper_mode', True) else "LIVE"
        from risk.degrader import LEVELS
        level = int(state.get('bot.degradation_level', 0))
        mode = LEVELS.get(level, {}).get('name', 'NORMAL')
        msg = (
            f"🦞 STATUS\n"
            f"Mode: {paper} | {mode} (level {level})\n"
            f"Regime: {state.get('bot.current_regime', 'RANGING')}\n"
            f"Bankroll: ${float(state.get('stats.bankroll', state.get('bankroll', 0.0))):.2f}\n"
            f"Open positions: {len(state.get('positions.open', []))}\n"
            f"Win Rate: {float(state.get('stats.win_rate_10', 0.5)):.0%} (10) | {float(state.get('stats.win_rate_20', 0.5)):.0%} (20)\n"
            f"Coverage: {' | '.join(tags)}"
        )
        await update.message.reply_text(msg)

    async def cmd_bankroll(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._authorized(update):
            return
        b = float(state.get('stats.bankroll', state.get('bankroll', 0.0)))
        pnl = float(state.get('stats.pnl_session', 0.0))
        hw = float(state.get('stats.high_watermark', b))
        dd = float(state.get('stats.drawdown_pct', 0.0))
        await update.message.reply_text(
            f"💰 Bankroll: ${b:.2f}\n"
            f"📈 Session PnL: ${pnl:+.2f}\n"
            f"🏔 High Watermark: ${hw:.2f}\n"
            f"📉 Drawdown: {dd:.1%}"
        )

    async def cmd_plans(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._authorized(update):
            return
        lines = ['📋 PLAN STATUS']
        for i in range(1, 13):
            plan = f'PLAN_{i:02d}'
            wr = float(state.get(f'stats.win_rate_10.{plan}', 0.5))
            ucb = float(state.get(f'plan.{plan}.ucb_score', 0.0))
            lines.append(f"  {plan}: WR={wr:.0%} UCB={ucb:.2f}")
        await update.message.reply_text('\n'.join(lines))

    async def cmd_positions(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._authorized(update):
            return
        positions = state.get('positions.open', [])
        if not positions:
            await update.message.reply_text('No open positions.')
            return
        lines = ['📊 OPEN POSITIONS']
        for a in positions:
            entry = float(state.get(f'position.{a}.entry_price', 0.0))
            direction = state.get(f'position.{a}.direction', '?')
            plan = state.get(f'position.{a}.plan', '?')
            lines.append(f"  {a} {plan} {direction} @ {entry:.3f}")
        await update.message.reply_text('\n'.join(lines))

    async def cmd_trades(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._authorized(update):
            return
        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                rows = await (await db.execute(
                    'SELECT asset, strategy, direction, pnl_pct, exit_reason FROM trades ORDER BY id DESC LIMIT 10'
                )).fetchall()
            if not rows:
                await update.message.reply_text('No trades yet.')
                return
            lines = ['📜 LAST 10 TRADES']
            for r in rows:
                emoji = '✅' if float(r['pnl_pct'] or 0) > 0 else '❌'
                lines.append(f"  {emoji} {r['asset']} {r['strategy']} {r['direction']} {float(r['pnl_pct'] or 0):+.1%} ({r['exit_reason']})")
            await update.message.reply_text('\n'.join(lines))
        except Exception:
            await update.message.reply_text('Error reading trades.')

    async def cmd_performance(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._authorized(update):
            return
        wr10 = float(state.get('stats.win_rate_10', 0.5))
        wr20 = float(state.get('stats.win_rate_20', 0.5))
        trades = int(state.get('stats.trades_this_session', 0))
        await update.message.reply_text(
            f"📈 PERFORMANCE\n"
            f"Win Rate (10): {wr10:.0%}\n"
            f"Win Rate (20): {wr20:.0%}\n"
            f"Trades this session: {trades}"
        )

    async def cmd_regime(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._authorized(update):
            return
        await update.message.reply_text(
            f"🧠 REGIME\n"
            f"Current: {state.get('bot.current_regime', 'RANGING')}\n"
            f"HMM Confidence: {float(state.get('bot.regime_confidence', 0.0)):.0%}\n"
            f"Trend Score: {float(state.get('regime.trend_score', 0.5)):.2f}\n"
            f"Volatility Ratio: {float(state.get('regime.volatility_ratio', 1.0)):.2f}\n"
            f"Avg Correlation: {float(state.get('regime.avg_correlation', 0.8)):.2f}"
        )

    async def cmd_coverage(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._authorized(update):
            return
        lines = ['📊 COVERAGE']
        for a in ['BTC', 'ETH', 'SOL', 'XRP']:
            c = int(state.get(f'coverage.window_covered.{a}', 0))
            t = int(state.get(f'coverage.window_total.{a}', 0))
            pct = (c / t * 100) if t else 0.0
            lines.append(f"  {a}: {pct:.0f}% ({c}/{t})")
        await update.message.reply_text('\n'.join(lines))

    async def cmd_signals(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._authorized(update):
            return
        import json
        from pathlib import Path
        try:
            w = json.loads(Path('data/signal_weights.json').read_text())
            ranked = sorted(w.items(), key=lambda x: x[1], reverse=True)
            lines = ['⚡ SIGNAL WEIGHTS']
            for name, weight in ranked:
                lines.append(f"  {name}: {weight:.2f}")
            await update.message.reply_text('\n'.join(lines))
        except Exception:
            await update.message.reply_text('Unable to read signal weights.')

    async def cmd_learning(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._authorized(update):
            return
        l5_loss = float(state.get('learning.l5.last_loss', 0.0))
        l5_lr = float(state.get('learning.l5.learning_rate', 0.01))
        l7_mult = float(state.get('learning.l7.rl_sizer.multiplier', 1.0))
        regime_conf = float(state.get('bot.regime_confidence', 0.0))
        await update.message.reply_text(
            f"🔬 LEARNING STATUS\n"
            f"L5 Gradient: loss={l5_loss:.4f} lr={l5_lr:.4f}\n"
            f"L7 RL Sizer: mult={l7_mult:.2f}\n"
            f"L3 HMM: confidence={regime_conf:.0%}"
        )

    async def cmd_thought_train(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._authorized(update):
            return
        last = state.get('risk.thought_train.last', {})
        if not last:
            await update.message.reply_text('No thought trains recorded.')
            return
        await update.message.reply_text(
            f"🧠 LAST THOUGHT TRAIN\n"
            f"Trigger: {last.get('trigger_reason')}\n"
            f"Pattern: {last.get('loss_pattern')}\n"
            f"Regime: {last.get('regime_at_time')}\n"
            f"Changes: {last.get('changes_made')}"
        )

    async def cmd_pause(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._authorized(update):
            return
        state.set_sync('bot.paused', True)
        await update.message.reply_text('⏸ Trading paused.')

    async def cmd_resume(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._authorized(update):
            return
        state.set_sync('bot.paused', False)
        state.set_sync('bot.hard_stopped', False)
        await update.message.reply_text('▶️ Trading resumed.')

    async def cmd_emergency(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._authorized(update):
            return
        state.set_sync('bot.emergency_stopped', True)
        await update.message.reply_text('🛑 Emergency stop activated.')

    async def cmd_config(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._authorized(update):
            return
        from core.config import config
        version = config.get('version', 1)
        await update.message.reply_text(f"⚙️ Config version: {version}")

    async def cmd_rollback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._authorized(update):
            return
        from pathlib import Path
        versions = sorted(Path('data/versions').glob('signal_weights_*.json'))
        if not versions:
            await update.message.reply_text('No versions available.')
            return
        target = versions[-1]
        if context.args and context.args[0].isdigit():
            idx = int(context.args[0])
            if 0 <= idx < len(versions):
                target = versions[idx]
        Path('data/signal_weights.json').write_text(target.read_text())
        await update.message.reply_text(f'Rolled back weights to {target.name}')

    async def cmd_paper_on(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._authorized(update):
            return
        state.set_sync('bot.paper_mode', True)
        await update.message.reply_text('📝 Paper mode ON.')

    async def cmd_paper_off(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._authorized(update):
            return
        state.set_sync('bot.paper_mode', False)
        await update.message.reply_text('🔴 LIVE mode activated.')

    async def on_stoploss(self, event: dict) -> None:
        await self.send(f"❌ STOP LOSS {event.get('asset')} {event.get('plan')} {float(event.get('pnl_pct', 0.0)):+.1%}")

    async def on_coverage_alert(self, event: dict) -> None:
        await self.send(f"⚠️ Coverage alert {event.get('asset')} gap {float(event.get('gap_minutes', 0.0)):.1f}m")

    async def on_coverage_failure(self, event: dict) -> None:
        await self.send(f"🚨 Coverage failure {event.get('asset')} reasons={event.get('reasons')}")

    async def on_regime_changed(self, event: dict) -> None:
        await self.send(f"🔄 Regime: {event.get('old')} → {event.get('new')}")

    async def on_degradation_changed(self, event: dict) -> None:
        await self.send(f"⚠️ Degradation: level {event.get('old')} → {event.get('new')}")

    async def on_thought_train(self, event: dict) -> None:
        await self.send(
            f"🧠 THOUGHT TRAIN — {event.get('trigger_reason')}\n"
            f"📊 Pattern: {event.get('loss_pattern')}\n"
            f"🔧 Changes: {event.get('changes_made')}"
        )

    async def run(self) -> None:
        bus.subscribe('STOP_LOSS_HIT', self.on_stoploss)
        bus.subscribe('COVERAGE_ALERT', self.on_coverage_alert)
        bus.subscribe('COVERAGE_FAILURE', self.on_coverage_failure)
        bus.subscribe('REGIME_CHANGED', self.on_regime_changed)
        bus.subscribe('DEGRADATION_LEVEL_CHANGED', self.on_degradation_changed)
        bus.subscribe('THOUGHT_TRAIN_COMPLETED', self.on_thought_train)

        if not self.enabled or not self.app:
            while True:
                await asyncio.sleep(3600)

        handlers = [
            ('status', self.cmd_status), ('bankroll', self.cmd_bankroll),
            ('plans', self.cmd_plans), ('positions', self.cmd_positions),
            ('trades', self.cmd_trades), ('performance', self.cmd_performance),
            ('regime', self.cmd_regime), ('coverage', self.cmd_coverage),
            ('signals', self.cmd_signals), ('learning', self.cmd_learning),
            ('thought_train', self.cmd_thought_train),
            ('pause', self.cmd_pause), ('resume', self.cmd_resume),
            ('emergency_stop', self.cmd_emergency),
            ('config', self.cmd_config), ('rollback', self.cmd_rollback),
            ('paper_on', self.cmd_paper_on), ('paper_off', self.cmd_paper_off),
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
