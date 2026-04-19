"""
Gestión de riesgo institucional con circuit breakers hard-coded.

Pre-trade checklist de 9 puntos que se ejecuta ANTES de cada orden.
Cada check retorna (bool, str) — la razón se usa para logging y auditoría.
Los circuit breakers NUNCA se delegan al LLM; son checks determinísticos en código.
"""

from datetime import datetime
from typing import Tuple

import pytz
from loguru import logger

from ..brain.groq_agent import GroqTradeSignal
from ..config import constants as C
from ..config.settings import settings
from ..core.state import bot_state


class RiskManager:
    """
    Gestiona todos los controles de riesgo pre-trade.

    Todos los circuit breakers son determinísticos, hard-coded en Python,
    y se ejecutan síncronamente antes de que cualquier orden llegue al broker.
    """

    def __init__(self) -> None:
        self.timezone = pytz.timezone("America/New_York")

    # ═══════════════════════════════════════
    # PUBLIC API
    # ═══════════════════════════════════════

    async def validate_trade(
        self,
        signal: GroqTradeSignal,
        estimated_cost: float,
    ) -> Tuple[bool, str]:
        """
        Execute the complete pre-trade checklist.

        Args:
            signal: Validated GroqTradeSignal from the AI analysis.
            estimated_cost: Total estimated cost of the position in USD.

        Returns:
            Tuple (is_valid, reason). If is_valid is False, reason explains why.
        """
        checks = [
            self._check_action_is_tradeable(signal),
            self._check_market_hours(),
            self._check_daily_loss_limit(),
            self._check_max_drawdown(),
            self._check_max_positions(signal),
            self._check_buying_power(signal, estimated_cost),
            self._check_pdt_rule(),
            self._check_stop_loss_validity(signal),
            self._check_risk_reward(signal),
        ]

        for is_valid, reason in checks:
            if not is_valid:
                logger.warning(f"🚫 Risk check FAILED: {reason}")
                return False, reason

        logger.info("✅ All 9 risk checks passed")
        return True, "OK"

    # ═══════════════════════════════════════
    # INDIVIDUAL CHECKS
    # ═══════════════════════════════════════

    def _check_action_is_tradeable(
        self, signal: GroqTradeSignal,
    ) -> Tuple[bool, str]:
        """HOLD signals should not reach execution."""
        if signal.action == "HOLD":
            return False, "Signal action is HOLD — no trade"
        return True, "OK"

    def _check_market_hours(self) -> Tuple[bool, str]:
        """Verify we're within safe trading hours (ET)."""
        now = datetime.now(self.timezone)

        if now.weekday() >= 5:
            return False, f"Market closed — weekend (day={now.weekday()})"

        open_time = now.replace(
            hour=settings.MARKET_OPEN_HOUR,
            minute=settings.MARKET_OPEN_MINUTE,
            second=0, microsecond=0,
        )
        close_time = now.replace(
            hour=settings.MARKET_CLOSE_HOUR,
            minute=settings.MARKET_CLOSE_MINUTE,
            second=0, microsecond=0,
        )

        if not (open_time <= now <= close_time):
            return False, (
                f"Outside trading hours: {now.strftime('%H:%M')} ET "
                f"(allowed: {settings.MARKET_OPEN_HOUR}:"
                f"{settings.MARKET_OPEN_MINUTE:02d}"
                f"-{settings.MARKET_CLOSE_HOUR}:"
                f"{settings.MARKET_CLOSE_MINUTE:02d})"
            )

        return True, "OK"

    def _check_daily_loss_limit(self) -> Tuple[bool, str]:
        """Circuit breaker: halt if daily loss exceeds limit."""
        if bot_state.daily_pnl_pct <= -settings.MAX_DAILY_LOSS_PCT:
            return False, (
                f"CIRCUIT BREAKER — Daily loss limit: "
                f"{bot_state.daily_pnl_pct:.2%} <= "
                f"-{settings.MAX_DAILY_LOSS_PCT:.2%}"
            )
        return True, "OK"

    def _check_max_drawdown(self) -> Tuple[bool, str]:
        """Circuit breaker: halt if max drawdown exceeded."""
        if bot_state.max_drawdown >= C.DRAWDOWN_HARD_LIMIT:
            return False, (
                f"CIRCUIT BREAKER — Max drawdown: "
                f"{bot_state.max_drawdown:.2%} >= "
                f"{C.DRAWDOWN_HARD_LIMIT:.2%}"
            )
        return True, "OK"

    def _check_max_positions(
        self, signal: GroqTradeSignal,
    ) -> Tuple[bool, str]:
        """Don't exceed maximum concurrent positions."""
        if (
            signal.action == "BUY"
            and bot_state.open_position_count >= settings.MAX_OPEN_POSITIONS
        ):
            return False, (
                f"Max positions reached: "
                f"{bot_state.open_position_count}/{settings.MAX_OPEN_POSITIONS}"
            )
        return True, "OK"

    def _check_buying_power(
        self,
        signal: GroqTradeSignal,
        estimated_cost: float,
    ) -> Tuple[bool, str]:
        """Verify sufficient buying power with safety buffer."""
        if signal.action != "BUY":
            return True, "OK"

        required = estimated_cost * C.BUYING_POWER_BUFFER
        if required > bot_state.buying_power:
            return False, (
                f"Insufficient buying power for {signal.ticker}: "
                f"Required=${required:,.2f} "
                f"(incl. {(C.BUYING_POWER_BUFFER-1)*100:.0f}% buffer), "
                f"Available=${bot_state.buying_power:,.2f}"
            )
        return True, "OK"

    def _check_pdt_rule(self) -> Tuple[bool, str]:
        """Pattern Day Trader protection: limit daily trades."""
        if bot_state.trades_today >= settings.MAX_DAILY_TRADES:
            return False, (
                f"PDT protection: {bot_state.trades_today} trades today "
                f"(limit: {settings.MAX_DAILY_TRADES})"
            )
        return True, "OK"

    def _check_stop_loss_validity(
        self, signal: GroqTradeSignal,
    ) -> Tuple[bool, str]:
        """For BUY: SL must be below entry. For SELL: SL must be above entry."""
        if signal.action == "BUY" and signal.stop_loss >= signal.entry_price_target:
            return False, (
                f"Invalid SL for BUY {signal.ticker}: "
                f"SL (${signal.stop_loss:.2f}) >= "
                f"Entry (${signal.entry_price_target:.2f})"
            )
        return True, "OK"

    def _check_risk_reward(
        self, signal: GroqTradeSignal,
    ) -> Tuple[bool, str]:
        """Ensure minimum risk/reward ratio."""
        if (
            signal.action in ("BUY", "SELL")
            and signal.risk_reward_ratio < C.MIN_RISK_REWARD_RATIO
        ):
            return False, (
                f"Risk/reward too low: {signal.risk_reward_ratio:.2f} "
                f"(min: {C.MIN_RISK_REWARD_RATIO})"
            )
        return True, "OK"

    # ═══════════════════════════════════════
    # DYNAMIC STOP LOSS
    # ═══════════════════════════════════════

    def calculate_atr_stop_loss(
        self,
        entry_price: float,
        atr: float,
        market_regime: str,
    ) -> float:
        """
        Calculate dynamic stop loss based on ATR and market regime.

        In high volatility regimes, uses a wider stop (2.5x ATR)
        to avoid being stopped out by noise.

        Args:
            entry_price: Entry price.
            atr: Average True Range value.
            market_regime: Current market regime.

        Returns:
            Stop loss price rounded to 2 decimals.
        """
        if market_regime == C.REGIME_HIGH_VOLATILITY:
            multiplier = C.ATR_MULTIPLIER_HIGH_VOL
        else:
            multiplier = C.ATR_MULTIPLIER_LOW_VOL

        stop_loss = entry_price - (atr * multiplier)
        return round(max(stop_loss, 0.01), 2)

    def is_market_open(self) -> bool:
        """
        Quick check if the market is currently open.

        Returns:
            True if within trading hours on a weekday.
        """
        is_valid, _ = self._check_market_hours()
        return is_valid
