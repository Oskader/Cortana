from loguru import logger
from ..core.state import bot_state
from ..config.settings import settings

class PortfolioSizer:
    def __init__(self, win_rate: float = 0.5, avg_win: float = 2.0, avg_loss: float = 1.0):
        """
        Inicia con valores por defecto hasta que las estadísticas reales estén disponibles.
        """
        self.win_rate = win_rate
        self.avg_win = avg_win
        self.avg_loss = avg_loss

    def calculate_kelly_size(self, equity: float) -> float:
        """
        Calcula el tamaño de la posición usando Half-Kelly.
        formula: f* = (p*b - q) / b
        f: fracción de kelly
        p: probabilidad de ganar (win_rate)
        q: probabilidad de perder (1 - p)
        b: ratio ganar/perder (avg_win / avg_loss)
        """
        if self.avg_loss == 0: return equity * 0.01
        
        b = self.avg_win / self.avg_loss
        p = self.win_rate
        q = 1 - p
        
        kelly_f = (p * b - q) / b if b != 0 else 0
        
        # Half-Kelly (más conservador)
        half_kelly = kelly_f / 2
        
        # Aplicar límites de seguridad
        safe_size = max(0.01, min(half_kelly, settings.MAX_POSITION_SIZE_PCT))
        
        position_value = equity * safe_size
        logger.info(f"Kelly Calc: WR={p:.2%}, B={b:.2f} -> Half-Kelly Share: {half_kelly:.2%}. Safe Size: {safe_size:.2%}")
        
        return position_value

    def get_quantity(self, ticker: str, price: float) -> int:
        """Determina la cantidad exacta de acciones a comprar"""
        equity = bot_state.equity if bot_state.equity > 0 else 1000 # fallback
        monto_a_invertir = self.calculate_kelly_size(equity)
        
        if price <= 0: return 0
        
        qty = int(monto_a_invertir / price)
        logger.info(f"Sizing for {ticker}: Equity=${equity:,.2f}, Target=${monto_a_invertir:,.2f} -> Qty={qty}")
        
        return qty
