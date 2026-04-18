from loguru import logger
from ..config.settings import settings
from ..core.state import bot_state
from datetime import datetime
import pytz

class RiskManager:
    def __init__(self):
        self.timezone = pytz.timezone("America/New_York")

    def is_market_open(self) -> bool:
        """Verifica si el mercado está abierto y no estamos en los minutos prohibidos"""
        now = datetime.now(self.timezone)
        
        # Horario de operación
        open_time = now.replace(hour=settings.MARKET_OPEN_HOUR, minute=settings.MARKET_OPEN_MINUTE, second=0)
        close_time = now.replace(hour=settings.MARKET_CLOSE_HOUR, minute=settings.MARKET_CLOSE_MINUTE, second=0)
        
        if now.weekday() >= 5:
            return False
            
        return open_time <= now <= close_time

    async def validate_trade(self, signal: dict) -> bool:
        """
        Checklist pre-trade de nivel institucional.
        """
        ticker = signal.get("ticker")
        action = signal.get("action")
        
        if action == "HOLD":
            return False

        # 1. Market Hours
        if not self.is_market_open():
            logger.warning(f"Riesgo: Intento de operar fuera de horario para {ticker}")
            return False

        # 2. Daily Loss Limit
        if bot_state.daily_pnl_pct <= -settings.MAX_DAILY_LOSS_PCT:
            logger.error(f"CIRCUIT BREAKER: Pérdida diaria máxima alcanzada ({bot_state.daily_pnl_pct:.2%})")
            return False

        # 3. Max Open Positions
        if action == "BUY" and len(bot_state.positions) >= settings.MAX_OPEN_POSITIONS:
            logger.warning(f"Riesgo: Máximo de posiciones abiertas alcanzado ({settings.MAX_OPEN_POSITIONS})")
            return False

        # 4. Drawdown Guard
        if bot_state.max_drawdown >= 0.05: # 5% drawdown guard
            logger.error(f"CIRCUIT BREAKER: Max Drawdown alcanzado. Deteniendo bot.")
            await bot_state.toggle_running(False)
            return False

        # 5. Buying Power Check
        # Se asume que el portfolio_sizer ya calculó una cantidad válida, 
        # pero aquí verificamos disponibilidad real con un buffer.
        buffer = 1.10 # 10% buffer
        estimated_cost = signal.get("entry_price_target", 0) * signal.get("qty", 0)
        if action == "BUY" and (estimated_cost * buffer) > bot_state.buying_power:
            logger.warning(f"Riesgo: Buying power insuficiente para {ticker}. Requerido: {estimated_cost}, Disponible: {bot_state.buying_power}")
            return False

        return True

    def calculate_atr_stop_loss(self, entry_price: float, atr: float, vix: float) -> float:
        """Calcula SL dinámico basado en ATR y Volatilidad (VIX)"""
        multiplier = 1.5 if vix < 20 else 2.5
        return entry_price - (atr * multiplier)
