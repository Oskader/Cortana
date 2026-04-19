"""
Position sizing con Half-Kelly Criterion usando estadísticas reales.

Ajusta el tamaño de posición según:
    - Win rate y average win/loss del trade journal (cuando hay suficiente data)
    - Régimen de mercado (50% del tamaño en alta volatilidad)
    - Cap máximo del 5% del portfolio por posición
"""

from loguru import logger

from ..config import constants as C
from ..config.settings import settings
from ..core.state import bot_state


class PortfolioSizer:
    """
    Calcula el tamaño de posición óptimo usando Half-Kelly Criterion.

    Usa estadísticas reales del TradeJournal cuando hay suficiente
    historial (>= 20 trades), con fallback a valores conservadores.
    """

    def __init__(
        self,
        win_rate: float = 0.50,
        avg_win: float = 2.0,
        avg_loss: float = 1.0,
    ) -> None:
        """
        Initialize with default statistics.

        Args:
            win_rate: Probability of winning (0.0 - 1.0).
            avg_win: Average dollar gain on winning trades.
            avg_loss: Average dollar loss on losing trades.
        """
        self.win_rate = win_rate
        self.avg_win = avg_win
        self.avg_loss = avg_loss

    def update_stats_from_journal(self, stats: dict) -> None:
        """
        Update Kelly statistics with real data from the trade journal.

        Only updates if there are enough trades for statistical significance.

        Args:
            stats: Dict with 'win_rate', 'avg_win', 'avg_loss', 'trades'.
        """
        if stats.get("trades", 0) >= C.KELLY_MIN_SAMPLE_SIZE:
            self.win_rate = stats.get("win_rate", self.win_rate)
            self.avg_win = stats.get("avg_win", self.avg_win)
            self.avg_loss = max(stats.get("avg_loss", self.avg_loss), 0.01)
            logger.info(
                f"Kelly stats updated from journal: "
                f"WR={self.win_rate:.2%}, "
                f"AvgW=${self.avg_win:.2f}, "
                f"AvgL=${self.avg_loss:.2f} "
                f"(from {stats.get('trades')} trades)"
            )
        else:
            logger.debug(
                f"Not enough trades for real Kelly stats "
                f"({stats.get('trades', 0)} < {C.KELLY_MIN_SAMPLE_SIZE}), "
                f"using defaults"
            )

    def calculate_kelly_fraction(self) -> float:
        """
        Calculate the Half-Kelly fraction.

        Formula: f* = (p * b - q) / b
        Where: p=win_rate, q=1-p, b=avg_win/avg_loss

        Returns:
            Fraction of portfolio to risk (clamped to safe bounds).
        """
        if self.avg_loss <= 0:
            return C.KELLY_MIN_FRACTION

        b = self.avg_win / self.avg_loss  # Win/Loss ratio
        p = self.win_rate
        q = 1.0 - p

        full_kelly = (p * b - q) / b if b > 0 else 0
        half_kelly = full_kelly / 2.0

        # Clamp to safe bounds
        safe_fraction = max(
            C.KELLY_MIN_FRACTION,
            min(half_kelly, settings.MAX_POSITION_SIZE_PCT),
        )
        return safe_fraction

    def calculate_position_value(
        self,
        market_regime: str,
    ) -> float:
        """
        Calculate the position value in USD.

        Args:
            market_regime: Current market regime for size adjustment.

        Returns:
            Dollar amount to invest, adjusted by regime.
        """
        equity = bot_state.equity if bot_state.equity > 0 else C.KELLY_FALLBACK_EQUITY

        kelly_fraction = self.calculate_kelly_fraction()
        position_value = equity * kelly_fraction

        # Reduce size in high volatility
        if market_regime == C.REGIME_HIGH_VOLATILITY:
            position_value *= C.HIGH_VOL_SIZE_REDUCTION
            logger.info(
                f"High vol regime: position reduced by "
                f"{(1 - C.HIGH_VOL_SIZE_REDUCTION):.0%}"
            )

        # Absolute cap
        max_position = equity * settings.MAX_POSITION_SIZE_PCT
        position_value = min(position_value, max_position)

        logger.info(
            f"Position sizing: Kelly={kelly_fraction:.2%}, "
            f"Regime={market_regime}, "
            f"Size=${position_value:,.2f} "
            f"({position_value/equity:.2%} of ${equity:,.2f} equity)"
        )
        return position_value

    def get_position_value(
        self,
        ticker: str,
        market_regime: str,
    ) -> float:
        """
        Determine the exact notional amount to risk.
        Fractional shares support.

        Args:
            ticker: Stock ticker symbol.
            market_regime: Current market regime.

        Returns:
            Float dollar amount to invest (0 if calculation fails).
        """
        position_value = self.calculate_position_value(
            market_regime=market_regime,
        )

        # Usar el Liquidity Cushion para verificar que tenemos suficiente efectivo total disponible
        cushion = max(bot_state.equity * float(settings.model_dump().get("LIQUIDITY_CUSHION_PCT", 0.1)), 1.0)
        available_cash = bot_state.buying_power - cushion

        if position_value > available_cash:
            logger.warning(
                f"Sizing {ticker}: Reduced size from ${position_value:.2f} "
                f"to ${available_cash:.2f} due to liquidity cushion constraints."
            )
            position_value = max(available_cash, 0.0)

        if position_value < 1.00:  # Minimum valid order Alpaca is $1.00 usually
            logger.warning(
                f"Sizing {ticker}: Resulting value ${position_value:.2f} < $1.00 minimum. "
                "Canceled."
            )
            return 0.0

        position_value = round(position_value, 2)
        logger.info(
            f"Sizing {ticker}: Final notional position value = ${position_value:,.2f}"
        )
        return position_value
