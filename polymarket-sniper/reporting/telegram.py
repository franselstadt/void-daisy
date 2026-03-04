"""Telegram command handlers and alerting."""

from __future__ import annotations

import asyncio
import os
from typing import Any

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from core.event_bus import bus
from core.logger import logger
from core.state import AppState
from learning.trade_logger import TradeLogger
from reporting.metrics import Metrics


class TelegramReporter:
    """Async telegram bot that supports ops commands and alerts."""

    def __init__(self, state: AppState, trade_logger: TradeLogger, metrics: Metrics) -> None:
        self.state = state
        self.trade_logger = trade_logger
        self.metrics = metrics
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.enabled = bool(token and self.chat_id)
        self.app = Application.builder().token(token).build() if self.enabled else None

    async def _status_text(self) -> str:
        snap = await self.state.snapshot()
        return (
            f"Mode: {snap.get('degradation_level', 0)}\n"
            f"Bankroll: ${snap.get('bankroll', 0.0):.2f}\n"
            f"Open positions: {len(snap.get('open_positions', {}))}\n"
            f"Paused: {snap.get('bot', {}).get('paused', False)}"
        )

    async def cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.message.reply_text(await self._status_text())

    async def cmd_bankroll(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        bankroll = await self.state.get("bankroll", default=0.0)
        await update.message.reply_text(f"Bankroll: ${float(bankroll):.2f}")

    async def cmd_trades(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        rows = await self.trade_logger.fetch_recent_trades(10)
        if not rows:
            await update.message.reply_text("No trades yet.")
            return
        lines = [f"{r['asset']} {r['direction']} {r['pnl_pct']:.1%} ({r['exit_reason']})" for r in rows]
        await update.message.reply_text("\n".join(lines))

    async def cmd_signals(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.message.reply_text("Use /config and weights file for current signal profile.")

    async def cmd_pause(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        bot = await self.state.get("bot", default={})
        bot["paused"] = True
        await self.state.set("bot", value=bot)
        await update.message.reply_text("Trading paused.")

    async def cmd_resume(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        bot = await self.state.get("bot", default={})
        bot["paused"] = False
        await self.state.set("bot", value=bot)
        await update.message.reply_text("Trading resumed.")

    async def cmd_emergency_stop(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        bot = await self.state.get("bot", default={})
        bot["emergency_stopped"] = True
        await self.state.set("bot", value=bot)
        await update.message.reply_text("Emergency stop activated.")

    async def cmd_degradation(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        level = await self.state.get("degradation_level", default=0)
        await update.message.reply_text(f"Degradation level: {level}")

    async def cmd_performance(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.message.reply_text(str(self.metrics.summary()))

    async def cmd_config(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        version = await self.state.get("version", default={})
        await update.message.reply_text(f"Config version: {version.get('config', 1)}")

    async def send_message(self, text: str) -> None:
        """Push message to configured chat if enabled."""
        if not self.enabled or not self.app:
            return
        try:
            await self.app.bot.send_message(chat_id=self.chat_id, text=text)
        except Exception as exc:  # noqa: BLE001
            logger.warning("telegram_send_failed", error=str(exc))

    async def on_trade_exited(self, event: dict[str, Any]) -> None:
        """Alert on large gains and stop losses."""
        self.metrics.on_exit(event)
        if event.get("exit_reason") == "STOP_LOSS_HIT":
            await self.send_message(f"STOP LOSS: {event.get('asset')} {event.get('pnl_pct', 0.0):.1%}")
        if float(event.get("pnl_pct", 0.0)) > 0.5:
            await self.send_message(f"Huge gain: {event.get('asset')} {event.get('pnl_pct', 0.0):.1%}")

    async def on_degradation_change(self, event: dict[str, Any]) -> None:
        await self.send_message(f"Mode changed: {event.get('profile', {}).get('name', event.get('new'))}")

    async def run(self) -> None:
        """Start command handlers and keep bot running."""
        bus.subscribe("TRADE_EXITED", self.on_trade_exited)
        bus.subscribe("DEGRADATION_LEVEL_CHANGED", self.on_degradation_change)
        if not self.enabled or not self.app:
            while True:
                await asyncio.sleep(3600)

        for name, handler in [
            ("status", self.cmd_status),
            ("bankroll", self.cmd_bankroll),
            ("trades", self.cmd_trades),
            ("signals", self.cmd_signals),
            ("pause", self.cmd_pause),
            ("resume", self.cmd_resume),
            ("emergency_stop", self.cmd_emergency_stop),
            ("degradation", self.cmd_degradation),
            ("performance", self.cmd_performance),
            ("config", self.cmd_config),
        ]:
            self.app.add_handler(CommandHandler(name, handler))

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
