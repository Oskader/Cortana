"""
Interfaz de Telegram para el bot Cortana.

Implementa:
    - Whitelist de chat IDs en TODOS los handlers
    - Comandos: /start, /status, /portfolio, /pause, /resume,
                /report, /trades, /risk, /help
    - Alertas con formato HTML rico
    - Inline keyboards para confirmación
    - Reporte diario automático via APScheduler
"""

import asyncio
from datetime import datetime
from typing import Any, Dict, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from ..config.settings import settings
from ..core.state import bot_state


class TelegramUI:
    """
    Interfaz de usuario de Telegram con autenticación por whitelist.

    Todos los comandos verifican el chat_id contra ALLOWED_CHAT_IDS
    antes de procesar cualquier solicitud.
    """

    def __init__(self) -> None:
        self.app = ApplicationBuilder().token(settings.TELEGRAM_TOKEN).build()
        self._journal = None  # Set by engine after init
        self._scheduler: Optional[AsyncIOScheduler] = None
        self._setup_handlers()

    def set_journal(self, journal: Any) -> None:
        """Inject the TradeJournal dependency (avoids circular imports)."""
        self._journal = journal

    def _setup_handlers(self) -> None:
        """Register all command and callback handlers."""
        commands = [
            ("start", self._cmd_start),
            ("status", self._cmd_status),
            ("portfolio", self._cmd_portfolio),
            ("pause", self._cmd_pause),
            ("resume", self._cmd_resume),
            ("report", self._cmd_report),
            ("trades", self._cmd_trades),
            ("risk", self._cmd_risk),
            ("help", self._cmd_help),
        ]
        for name, handler in commands:
            self.app.add_handler(CommandHandler(name, handler))

        self.app.add_handler(CallbackQueryHandler(self._button_handler))

    def _is_authorized(self, chat_id: int) -> bool:
        """Check if a chat ID is in the allowed whitelist."""
        authorized = chat_id in settings.ALLOWED_CHAT_IDS or chat_id == settings.TELEGRAM_CHAT_ID
        if not authorized:
            logger.warning(f"Unauthorized access attempt from chat_id: {chat_id}")
        return authorized

    # ═══════════════════════════════════════
    # COMMAND HANDLERS
    # ═══════════════════════════════════════

    async def _cmd_start(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Handle /start — Welcome message."""
        if not self._is_authorized(update.effective_chat.id):
            return
        
        commands_list = (
            "<b>Comandos Disponibles:</b>\n"
            "📊 /status — Diagnóstico del bot\n"
            "💼 /portfolio — Ver posiciones\n"
            "📈 /trades — Historial reciente\n"
            "🛡️ /risk — Métricas de performance\n"
            "📅 /report — Reporte diario manual\n"
            "⏸️ /pause — Detener trading\n"
            "▶️ /resume — Reanudar trading\n"
            "❓ /help — Este menú"
        )
        
        msg = (
            "👋 <b>Hola, soy Cortana.</b>\n\n"
            "Tus sistemas de trading están bajo mi supervisión.\n\n"
            f"{commands_list}"
        )
        await update.message.reply_html(msg)

    async def _cmd_status(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Handle /status — Bot diagnostics."""
        if not self._is_authorized(update.effective_chat.id):
            return

        system_status = "❇️ OPERATIVO" if bot_state.is_running else "🛑 PAUSADO"
        market_status = "✅ ABIERTO (Activo)" if bot_state.is_market_open else "💤 CERRADO (Inactivo)"
        pnl_emoji = "🟢" if bot_state.daily_pnl_pct >= 0 else "🔴"

        msg = (
            f"<b>DIAGNÓSTICO DE CORTANA</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"Entorno: <code>{settings.TRADING_MODE.upper()}</code>\n"
            f"Sistema: {system_status} | Mercado: {market_status}\n"
            f"Equity: <code>${bot_state.equity:,.2f}</code>\n"
            f"Buying Power: <code>${bot_state.buying_power:,.2f}</code>\n"
            f"{pnl_emoji} P&L Día: <code>{bot_state.daily_pnl_pct:+.2%} (${bot_state.daily_pnl:+,.2f})</code>\n"
            f"Drawdown: <code>{bot_state.max_drawdown:.2%}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔍 <b>Salud del Sistema:</b>\n"
            f"VIX Actual: <code>{bot_state.last_vix:.2f}</code>\n"
            f"Régimen: <code>{bot_state.market_regime}</code>\n"
            f"Historial Kelly: <code>{bot_state.kelly_trades} trades</code>\n"
            f"Posiciones: <code>{bot_state.open_position_count}/{settings.MAX_OPEN_POSITIONS}</code>\n"
            f"Trades hoy (PDT): <code>{bot_state.trades_today}/{settings.MAX_DAILY_TRADES}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"<i>Última actualización: {bot_state.last_update.strftime('%H:%M:%S')}</i>"
        )
        await update.message.reply_html(msg)

    async def _cmd_portfolio(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Handle /portfolio — Show open positions."""
        if not self._is_authorized(update.effective_chat.id):
            return

        if not bot_state.positions:
            await update.message.reply_text("📭 No hay posiciones abiertas.")
            return

        msg = "<b>PORTFOLIO ACTUAL</b>\n━━━━━━━━━━━━━━━━━━━━━\n"
        total_pnl = 0.0

        for sym, pos in bot_state.positions.items():
            emoji = "🟢" if pos.unrealized_pnl >= 0 else "🔴"
            msg += (
                f"{emoji} <b>{sym}</b>\n"
                f"   Qty: {pos.qty} | Entry: ${pos.entry_price:.2f}\n"
                f"   Current: ${pos.current_price:.2f} | "
                f"P&L: <code>{pos.unrealized_pnl_pct:+.2%} "
                f"(${pos.unrealized_pnl:+,.2f})</code>\n"
            )
            total_pnl += pos.unrealized_pnl

        total_emoji = "🟢" if total_pnl >= 0 else "🔴"
        msg += (
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"{total_emoji} Total P&L: <code>${total_pnl:+,.2f}</code>"
        )
        await update.message.reply_html(msg)

    async def _cmd_pause(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Handle /pause — Pause trading."""
        if not self._is_authorized(update.effective_chat.id):
            return
        await bot_state.toggle_running(False)
        await update.message.reply_text("🛑 Trading PAUSADO. Posiciones abiertas no se tocan.")

    async def _cmd_resume(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Handle /resume — Resume trading."""
        if not self._is_authorized(update.effective_chat.id):
            return
        await bot_state.toggle_running(True)
        await update.message.reply_text("✅ Trading REANUDADO. Escaneando mercado...")

    async def _cmd_report(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Handle /report — Daily performance report."""
        if not self._is_authorized(update.effective_chat.id):
            return

        msg = await self._generate_report_text()
        await update.message.reply_html(msg)

    async def _cmd_trades(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Handle /trades — Recent trade history."""
        if not self._is_authorized(update.effective_chat.id):
            return

        if not self._journal:
            await update.message.reply_text("📊 Trade journal no disponible.")
            return

        trades = await asyncio.to_thread(self._journal.get_recent_trades)
        if not trades:
            await update.message.reply_text("📭 Sin trades registrados.")
            return

        msg = "<b>ÚLTIMOS TRADES</b>\n━━━━━━━━━━━━━━━━━━━━━\n"
        for t in trades:
            pnl = t.get("pnl_dollar", 0)
            emoji = "✅" if pnl > 0 else "❌"
            msg += (
                f"{emoji} <b>{t.get('ticker')}</b> | "
                f"{t.get('side')} | "
                f"P&L: <code>${pnl:+.2f}</code> | "
                f"{t.get('exit_reason', 'N/A')}\n"
            )
        await update.message.reply_html(msg)

    async def _cmd_risk(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Handle /risk — Current risk metrics."""
        if not self._is_authorized(update.effective_chat.id):
            return

        if not self._journal:
            await update.message.reply_text("📊 Métricas no disponibles.")
            return

        metrics = await asyncio.to_thread(self._journal.get_performance_metrics)

        msg = (
            f"<b>MÉTRICAS DE RIESGO</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"Sharpe Ratio: <code>{metrics.get('sharpe_ratio', 0):.2f}</code>\n"
            f"Profit Factor: <code>{metrics.get('profit_factor', 0):.2f}</code>\n"
            f"Win Rate: <code>{metrics.get('win_rate', 0):.1%}</code>\n"
            f"Max Drawdown: <code>{metrics.get('max_drawdown_pct', 0):.2%}</code>\n"
            f"Total Trades: <code>{metrics.get('total_trades', 0)}</code>\n"
            f"Total P&L: <code>${metrics.get('total_pnl', 0):+,.2f}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"Daily P&L: <code>{bot_state.daily_pnl_pct:+.2%}</code>\n"
            f"Current DD: <code>{bot_state.max_drawdown:.2%}</code>"
        )
        await update.message.reply_html(msg)

    async def _cmd_help(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Handle /help — List all commands."""
        if not self._is_authorized(update.effective_chat.id):
            return

        msg = (
            "<b>COMANDOS DE CORTANA</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "/status — Estado del bot y diagnóstico\n"
            "/portfolio — Posiciones abiertas\n"
            "/report — Reporte del día\n"
            "/trades — Últimos trades realizados\n"
            "/risk — Métricas de riesgo y performance\n"
            "/pause — Pausar trading\n"
            "/resume — Reanudar trading\n"
            "/help — Este menú\n"
        )
        await update.message.reply_html(msg)

    # ═══════════════════════════════════════
    # CALLBACKS
    # ═══════════════════════════════════════

    async def _button_handler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Handle inline keyboard button presses."""
        query = update.callback_query
        if not self._is_authorized(query.message.chat_id):
            return

        await query.answer()
        logger.info(f"Button pressed: {query.data}")

        if query.data == "confirm_trade":
            await query.edit_message_text("✅ Trade confirmado.")
        elif query.data == "reject_trade":
            await query.edit_message_text("🚫 Trade rechazado.")

    # ═══════════════════════════════════════
    # ALERTS & NOTIFICATIONS
    # ═══════════════════════════════════════

    async def send_alert(
        self,
        text: str,
        parse_mode: str = "HTML",
        reply_markup: Optional[InlineKeyboardMarkup] = None,
    ) -> None:
        """
        Send an alert to all whitelisted chat IDs.

        Args:
            text: Message text (supports HTML formatting).
            parse_mode: Telegram parse mode (default: HTML).
            reply_markup: Optional inline keyboard.
        """
        for chat_id in settings.ALLOWED_CHAT_IDS:
            try:
                await self.app.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode=parse_mode,
                    reply_markup=reply_markup,
                )
            except Exception as e:
                logger.error(f"Error sending alert to {chat_id}: {e}")

    async def send_trade_alert(
        self,
        ticker: str,
        side: str,
        qty: int,
        price: float,
        stop_loss: float,
        take_profit: float,
        confidence: float,
        reasoning: str,
    ) -> None:
        """
        Send a formatted trade execution alert with details.

        Args:
            ticker: Stock symbol.
            side: BUY or SELL.
            qty: Number of shares.
            price: Entry price.
            stop_loss: Stop loss price.
            take_profit: Take profit price.
            confidence: AI confidence score.
            reasoning: AI reasoning summary.
        """
        emoji = "🟩" if side == "BUY" else "🟥"
        risk_per_share = abs(price - stop_loss)
        reward_per_share = abs(take_profit - price)
        rr = reward_per_share / risk_per_share if risk_per_share > 0 else 0

        msg = (
            f"{emoji} <b>TRADE EJECUTADO</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>{side} {qty} × {ticker}</b>\n"
            f"Entry: <code>${price:.2f}</code>\n"
            f"Stop Loss: <code>${stop_loss:.2f}</code>\n"
            f"Take Profit: <code>${take_profit:.2f}</code>\n"
            f"R:R = <code>{rr:.1f}</code>\n"
            f"Confidence: <code>{confidence:.0%}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"<i>{reasoning}</i>"
        )
        await self.send_alert(msg)

    # ═══════════════════════════════════════
    # DAILY REPORT
    # ═══════════════════════════════════════

    async def _generate_report_text(self) -> str:
        """Generate the daily report text."""
        summary: Dict[str, Any] = {}
        metrics: Dict[str, Any] = {}

        if self._journal:
            summary = await asyncio.to_thread(self._journal.get_daily_summary)
            metrics = await asyncio.to_thread(self._journal.get_performance_metrics)

        pnl = summary.get("total_pnl", 0)
        pnl_emoji = "🟢" if pnl >= 0 else "🔴"

        return (
            f"<b>📊 REPORTE DIARIO — CORTANA</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"📅 Fecha: {summary.get('date', 'N/A')}\n"
            f"Trades: {summary.get('total_trades', 0)} "
            f"(✅{summary.get('wins', 0)} / ❌{summary.get('losses', 0)})\n"
            f"{pnl_emoji} P&L día: <code>${pnl:+,.2f}</code>\n"
            f"Mejor trade: <code>${summary.get('best_trade', 0):+,.2f}</code>\n"
            f"Peor trade: <code>${summary.get('worst_trade', 0):+,.2f}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Métricas Acumuladas:</b>\n"
            f"Sharpe: {metrics.get('sharpe_ratio', 0):.2f} | "
            f"PF: {metrics.get('profit_factor', 0):.2f}\n"
            f"WR: {metrics.get('win_rate', 0):.1%} | "
            f"DD: {metrics.get('max_drawdown_pct', 0):.2%}\n"
            f"Total P&L: <code>${metrics.get('total_pnl', 0):+,.2f}</code>"
        )

    async def send_daily_report(self) -> None:
        """Generate and send the daily report to all whitelisted chats."""
        logger.info("Generating daily report...")
        msg = await self._generate_report_text()
        await self.send_alert(msg)

    def start_daily_report_scheduler(self) -> None:
        """
        Legacy: Daily report is now triggered by market close event in engine.
        """
        pass

    # ═══════════════════════════════════════
    # LIFECYCLE
    # ═══════════════════════════════════════

    async def run(self) -> None:
        """Initialize and start the Telegram bot polling."""
        logger.info("Starting Telegram bot...")
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling()
        self.start_daily_report_scheduler()

    async def stop(self) -> None:
        """Gracefully stop the Telegram bot and scheduler."""
        if self._scheduler:
            self._scheduler.shutdown(wait=False)
        await self.app.updater.stop()
        await self.app.stop()
        await self.app.shutdown()
        logger.info("Telegram bot stopped")
