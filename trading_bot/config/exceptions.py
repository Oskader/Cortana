"""
Excepciones personalizadas para el dominio de trading.
Cada excepción proporciona contexto específico para debugging en producción.
"""


class CortanaBotError(Exception):
    """Excepción base para todos los errores del bot Cortana."""
    pass


class InsufficientBuyingPowerError(CortanaBotError):
    """No hay suficiente poder de compra para ejecutar la orden."""

    def __init__(self, required: float, available: float, ticker: str) -> None:
        self.required = required
        self.available = available
        self.ticker = ticker
        super().__init__(
            f"Buying power insuficiente para {ticker}: "
            f"Requerido=${required:,.2f}, Disponible=${available:,.2f}"
        )


class MarketClosedError(CortanaBotError):
    """Intento de operar fuera de horario de mercado."""
    pass


class GroqParsingError(CortanaBotError):
    """Error al parsear o validar la respuesta de Groq."""

    def __init__(self, raw_response: str, reason: str) -> None:
        self.raw_response = raw_response
        self.reason = reason
        super().__init__(f"Error parsing Groq response: {reason}")


class RiskLimitExceededError(CortanaBotError):
    """Un límite de riesgo ha sido superado."""

    def __init__(self, check_name: str, detail: str) -> None:
        self.check_name = check_name
        self.detail = detail
        super().__init__(f"Risk limit [{check_name}]: {detail}")


class OrderExecutionError(CortanaBotError):
    """Error al ejecutar una orden en Alpaca."""

    def __init__(self, ticker: str, side: str, reason: str) -> None:
        self.ticker = ticker
        self.side = side
        super().__init__(f"Order execution failed: {side} {ticker} — {reason}")


class StateDesyncError(CortanaBotError):
    """El estado local está desincronizado con el broker."""
    pass
