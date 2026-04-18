from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, CallbackQueryHandler
from loguru import logger
from ..config.settings import settings
from ..core.state import bot_state
import html

class TelegramUI:
    def __init__(self):
        self.app = ApplicationBuilder().token(settings.TELEGRAM_TOKEN).build()
        self._setup_handlers()

    def _setup_handlers(self):
        self.app.add_handler(CommandHandler("start", self.start_cmd))
        self.app.add_handler(CommandHandler("status", self.status_cmd))
        self.app.add_handler(CommandHandler("portfolio", self.portfolio_cmd))
        self.app.add_handler(CommandHandler("pause", self.pause_cmd))
        self.app.add_handler(CommandHandler("resume", self.resume_cmd))
        
        # Callback para botones inline
        self.app.add_handler(CallbackQueryHandler(self.button_handler))

    async def start_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_chat.id not in settings.ALLOWED_CHAT_IDS:
            return
        await update.message.reply_text("👋 Hola, soy Cortana. Tus sistemas de trading están bajo mi supervisión. Usa /status para ver mi diagnóstico actual.")

    async def status_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_chat.id not in settings.ALLOWED_CHAT_IDS:
            return
            
        status_msg = (
            f"<b>DIAGNÓSTICO DE CORTANA</b>\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"Entorno: <code>{settings.TRADING_MODE.upper()}</code>\n"
            f"Estado: {'❇️ OPERATIVO' if bot_state.is_running else '🛑 DETENIDO'}\n"
            f"Equity: <code>${bot_state.equity:,.2f}</code>\n"
            f"P&L Día: <code>{bot_state.daily_pnl_pct:+.2%}</code>\n"
            f"Regimen: <code>{bot_state.market_regime}</code>\n"
            f"Posiciones: <code>{len(bot_state.positions)}/{settings.MAX_OPEN_POSITIONS}</code>"
        )
        await update.message.reply_html(status_msg)

    async def portfolio_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_chat.id not in settings.ALLOWED_CHAT_IDS:
            return
            
        if not bot_state.positions:
            await update.message.reply_text("No hay posiciones abiertas.")
            return

        msg = "<b>PORTFOLIO ACTUAL</b>\n━━━━━━━━━━━━━━━━\n"
        for sym, pos in bot_state.positions.items():
            emoji = "🟢" if pos.unrealized_pnl >= 0 else "🔴"
            msg += f"{emoji} <b>{sym}</b>: ${pos.current_price} ({pos.unrealized_pnl_pct:+.1%})\n"
            
        await update.message.reply_html(msg)

    async def pause_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await bot_state.toggle_running(False)
        await update.message.reply_text("🛑 Trading PAUSADO.")

    async def resume_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await bot_state.toggle_running(True)
        await update.message.reply_text("✅ Trading REANUDADO.")

    async def button_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        # Lógica para procesar confirmación de trades
        logger.info(f"Botón pulsado: {query.data}")

    async def send_alert(self, text: str, parse_mode: str = "HTML", reply_markup=None):
        """Envía una alerta a todos los IDs permitidos"""
        for chat_id in settings.ALLOWED_CHAT_IDS:
            try:
                await self.app.bot.send_message(
                    chat_id=chat_id, 
                    text=text, 
                    parse_mode=parse_mode,
                    reply_markup=reply_markup
                )
            except Exception as e:
                logger.error(f"Error enviando alerta a {chat_id}: {e}")

    async def run(self):
        logger.info("Iniciando Telegram Bot...")
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling()

    async def stop(self):
        await self.app.updater.stop()
        await self.app.stop()
        await self.app.shutdown()
