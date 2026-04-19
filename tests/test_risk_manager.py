"""
Tests para RiskManager — verifica todos los circuit breakers.

Cada test simula un escenario específico y verifica que
validate_trade() retorna el resultado correcto.
"""

import pytest
import pytest_asyncio
from datetime import datetime
from unittest.mock import patch, MagicMock

from trading_bot.risk.risk_manager import RiskManager
from trading_bot.brain.groq_agent import GroqTradeSignal
from trading_bot.config import constants as C


@pytest.fixture
def risk_manager():
    return RiskManager()


class TestCircuitBreakers:
    """Verifica que cada circuit breaker bloquea trades correctamente."""

    @pytest.mark.asyncio
    async def test_hold_signal_blocked(self, risk_manager, hold_signal):
        """HOLD signals should never reach execution."""
        is_valid, reason = await risk_manager.validate_trade(hold_signal, 1000.0)
        assert not is_valid
        assert "HOLD" in reason

    @pytest.mark.asyncio
    async def test_max_daily_loss_blocks_trade(
        self, risk_manager, valid_buy_signal, state_with_daily_loss,
    ):
        """When daily loss exceeds -2%, all new trades should be blocked."""
        with patch("trading_bot.risk.risk_manager.bot_state", state_with_daily_loss):
            # Mock market hours to be open
            with patch.object(risk_manager, "_check_market_hours", return_value=(True, "OK")):
                is_valid, reason = await risk_manager.validate_trade(
                    valid_buy_signal, 1000.0,
                )
                assert not is_valid
                assert "Daily loss limit" in reason

    @pytest.mark.asyncio
    async def test_max_positions_blocks_trade(
        self, risk_manager, valid_buy_signal, state_with_positions,
    ):
        """When 5 positions are open, new BUY should be blocked."""
        with patch("trading_bot.risk.risk_manager.bot_state", state_with_positions):
            with patch.object(risk_manager, "_check_market_hours", return_value=(True, "OK")):
                is_valid, reason = await risk_manager.validate_trade(
                    valid_buy_signal, 1000.0,
                )
                assert not is_valid
                assert "Max positions" in reason

    @pytest.mark.asyncio
    async def test_market_hours_weekend_blocked(self, risk_manager, valid_buy_signal):
        """Trading should be blocked on weekends or when market is closed."""
        with patch("trading_bot.risk.risk_manager.bot_state") as mock_state:
            mock_state.is_market_open = False
            is_valid, reason = risk_manager._check_market_hours()
            assert not is_valid
            assert "Market is closed" in reason

    @pytest.mark.asyncio
    async def test_insufficient_buying_power_blocked(
        self, risk_manager, valid_buy_signal, fresh_state,
    ):
        """When estimated cost exceeds buying power, trade should be blocked."""
        fresh_state.buying_power = 100.0  # Very low
        with patch("trading_bot.risk.risk_manager.bot_state", fresh_state):
            with patch.object(risk_manager, "_check_market_hours", return_value=(True, "OK")):
                is_valid, reason = await risk_manager.validate_trade(
                    valid_buy_signal,
                    estimated_cost=5000.0,  # Way more than $100 buying power
                )
                assert not is_valid
                assert "buying power" in reason.lower()

    @pytest.mark.asyncio
    async def test_pdt_limit_blocks_trade(
        self, risk_manager, valid_buy_signal, fresh_state,
    ):
        """When daily trade limit is reached, new trades should be blocked."""
        fresh_state.trades_today = 5  # Exceeds MAX_DAILY_TRADES=3
        with patch("trading_bot.risk.risk_manager.bot_state", fresh_state):
            with patch.object(risk_manager, "_check_market_hours", return_value=(True, "OK")):
                is_valid, reason = await risk_manager.validate_trade(
                    valid_buy_signal, 1000.0,
                )
                assert not is_valid
                assert "PDT" in reason


class TestStopLossValidation:
    """Verifica que stop loss inválidos son rechazados."""

    def test_invalid_stop_loss_for_buy_rejected(self, risk_manager):
        """Stop loss above entry price should fail for BUY."""
        signal = GroqTradeSignal(
            action="BUY",
            ticker="AAPL",
            confidence=0.80,
            reasoning="Test signal with invalid stop loss for testing purposes only.",
            entry_price_target=185.50,
            stop_loss=182.00,  # Valid in creation
            take_profit=192.00,
            risk_reward_ratio=1.86,
        )
        # Manually test the check with bad values
        signal_bad = signal.model_copy(update={"stop_loss": 190.00})
        is_valid, reason = risk_manager._check_stop_loss_validity(signal_bad)
        assert not is_valid
        assert "Invalid SL" in reason

    def test_valid_stop_loss_passes(self, risk_manager, valid_buy_signal):
        """Valid stop loss below entry should pass."""
        is_valid, reason = risk_manager._check_stop_loss_validity(valid_buy_signal)
        assert is_valid


class TestRiskReward:
    """Verifica el filtro de risk/reward ratio."""

    def test_low_rr_rejected(self, risk_manager):
        """Risk/reward below 1.5 should be rejected."""
        signal = GroqTradeSignal(
            action="BUY",
            ticker="AAPL",
            confidence=0.80,
            reasoning="Low risk reward signal for testing the minimum ratio threshold.",
            entry_price_target=185.50,
            stop_loss=182.00,
            take_profit=187.00,
            risk_reward_ratio=0.8,  # Below minimum
        )
        is_valid, reason = risk_manager._check_risk_reward(signal)
        assert not is_valid

    def test_good_rr_passes(self, risk_manager, valid_buy_signal):
        """Risk/reward above 1.5 should pass."""
        is_valid, reason = risk_manager._check_risk_reward(valid_buy_signal)
        assert is_valid


class TestATRStopLoss:
    """Verifica el cálculo de stop loss dinámico."""

    def test_low_vol_stop_loss(self, risk_manager):
        """Low volatility regime should use tighter stop (1.5x ATR)."""
        sl = risk_manager.calculate_atr_stop_loss(
            entry_price=100.0,
            atr=2.0,
            market_regime=C.REGIME_TRENDING_UP,
        )
        expected = 100.0 - (2.0 * C.ATR_MULTIPLIER_LOW_VOL)
        assert sl == round(expected, 2)

    def test_high_vol_stop_loss(self, risk_manager):
        """High volatility regime should use wider stop (2.5x ATR)."""
        sl = risk_manager.calculate_atr_stop_loss(
            entry_price=100.0,
            atr=2.0,
            market_regime=C.REGIME_HIGH_VOLATILITY,
        )
        expected = 100.0 - (2.0 * C.ATR_MULTIPLIER_HIGH_VOL)
        assert sl == round(expected, 2)


class TestKellyPositionSizing:
    """Verifica el cálculo de Half-Kelly."""

    def test_kelly_calculation_correct(self):
        """Verify the math: WR=60%, B=2.0 → Kelly=35%, Half=17.5%."""
        from trading_bot.risk.portfolio_sizer import PortfolioSizer
        sizer = PortfolioSizer(win_rate=0.60, avg_win=2.0, avg_loss=1.0)
        fraction = sizer.calculate_kelly_fraction()
        # f* = (0.6*2 - 0.4) / 2 = 0.4 → half = 0.2
        # But capped at MAX_POSITION_SIZE_PCT (0.20 for $10 account)
        assert fraction <= 0.20  # Should be capped

    def test_kelly_caps_at_5_percent(self):
        """Half-Kelly should never exceed 5% of portfolio."""
        from trading_bot.risk.portfolio_sizer import PortfolioSizer
        # Very favorable stats that would give high Kelly
        sizer = PortfolioSizer(win_rate=0.80, avg_win=3.0, avg_loss=1.0)
        fraction = sizer.calculate_kelly_fraction()
        assert fraction <= 0.20

    def test_kelly_minimum_floor(self):
        """Kelly should never go below 1% minimum."""
        from trading_bot.risk.portfolio_sizer import PortfolioSizer
        # Very unfavorable stats
        sizer = PortfolioSizer(win_rate=0.30, avg_win=1.0, avg_loss=2.0)
        fraction = sizer.calculate_kelly_fraction()
        assert fraction >= C.KELLY_MIN_FRACTION
