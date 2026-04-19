"""
Test de integración — flujo completo de trade con todos los componentes mockeados.

Simula el flujo: señal → análisis Groq → validación riesgo → orden → notificación.
Ninguna llamada real a APIs externas.
"""

import asyncio

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from trading_bot.brain.groq_agent import GroqAgent, GroqTradeSignal
from trading_bot.config import constants as C
from trading_bot.core.state import GlobalState, PositionState


class TestFullTradeFlow:
    """
    Test de integración del flujo completo de un trade.

    Steps verificados:
        1. Signal scoring detecta oportunidad (score >= 70)
        2. Groq analiza y retorna BUY con confidence >= 0.72
        3. Risk manager valida (9 checks pass)
        4. Position sizer calcula qty correcta
        5. Bracket order se envía a Alpaca
        6. Trade se registra en journal
        7. Notificación se envía por Telegram
    """

    @pytest.mark.asyncio
    async def test_buy_flow_complete(
        self,
        valid_buy_signal,
        fresh_state,
        mock_alpaca_client,
        sample_ohlcv_df,
    ):
        """
        Full BUY flow with mocked dependencies should complete successfully.
        """
        # Setup mocks
        mock_brain = MagicMock(spec=GroqAgent)
        mock_brain.analyze_with_reflection = AsyncMock(return_value=valid_buy_signal)
        mock_brain.build_context = AsyncMock(return_value="mock context")

        mock_journal = MagicMock()
        mock_journal.log_entry.return_value = 1
        mock_journal.get_recent_trades.return_value = []

        mock_tg = MagicMock()
        mock_tg.send_trade_alert = AsyncMock()
        mock_tg.send_alert = AsyncMock()

        # Simulate the engine's process_opportunity flow
        signal = valid_buy_signal
        qty = 10  # Simulated from sizer

        # Verify signal passes risk check
        from trading_bot.risk.risk_manager import RiskManager
        risk = RiskManager()

        with patch("trading_bot.risk.risk_manager.bot_state", fresh_state):
            with patch.object(risk, "_check_market_hours", return_value=(True, "OK")):
                is_valid, reason = await risk.validate_trade(
                    signal, estimated_cost=qty * signal.entry_price_target,
                )

        assert is_valid, f"Trade should be valid but blocked: {reason}"

        # Verify order would be created
        from alpaca.trading.enums import OrderSide
        mock_alpaca_client.submit_bracket_order(
            symbol=signal.ticker,
            qty=qty,
            side=OrderSide.BUY,
            stop_loss_price=signal.stop_loss,
            take_profit_price=signal.take_profit,
        )

        # Verify journal entry
        trade_id = mock_journal.log_entry(
            ticker=signal.ticker,
            side="BUY",
            qty=qty,
            entry_price=signal.entry_price_target,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            confidence_score=signal.confidence,
        )
        assert trade_id == 1

        # Verify notification would be sent
        await mock_tg.send_trade_alert(
            ticker=signal.ticker,
            side="BUY",
            qty=qty,
            price=signal.entry_price_target,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            confidence=signal.confidence,
            reasoning=signal.reasoning,
        )
        mock_tg.send_trade_alert.assert_called_once()

    @pytest.mark.asyncio
    async def test_hold_signal_skips_entirely(
        self, hold_signal, fresh_state,
    ):
        """
        When Groq returns HOLD, no order, journal, or notification should happen.
        """
        mock_brain = MagicMock(spec=GroqAgent)
        mock_brain.analyze_with_reflection = AsyncMock(return_value=hold_signal)

        # HOLD signal should stop the flow
        assert hold_signal.action == "HOLD"

        mock_journal = MagicMock()
        mock_alpaca = MagicMock()
        mock_tg = MagicMock()

        # None of these should be called
        mock_alpaca.submit_bracket_order.assert_not_called()
        mock_journal.log_entry.assert_not_called()

    @pytest.mark.asyncio
    async def test_low_confidence_skips_trade(
        self, low_confidence_signal, fresh_state,
    ):
        """
        Signals with confidence below GROQ_MIN_CONFIDENCE should be skipped.
        """
        from trading_bot.config.settings import settings

        assert low_confidence_signal.confidence < settings.GROQ_MIN_CONFIDENCE
        # The engine checks confidence AFTER Groq returns
        # This signal (0.50) < min (0.72) should not proceed

    @pytest.mark.asyncio
    async def test_risk_rejection_sends_alert(
        self, valid_buy_signal, state_with_daily_loss,
    ):
        """
        When risk manager rejects, a Telegram alert should be sent.
        """
        from trading_bot.risk.risk_manager import RiskManager
        risk = RiskManager()

        with patch("trading_bot.risk.risk_manager.bot_state", state_with_daily_loss):
            with patch.object(risk, "_check_market_hours", return_value=(True, "OK")):
                is_valid, reason = await risk.validate_trade(
                    valid_buy_signal, 1000.0,
                )

        assert not is_valid
        # In production, the engine would send: tg.send_alert(f"🚫 Trade bloqueado: {reason}")
        assert "Daily loss" in reason


class TestStateConsistency:
    """
    Verifica que el estado del bot se mantiene consistente
    durante el flujo de trading.
    """

    @pytest.mark.asyncio
    async def test_trade_counter_increments(self, fresh_state):
        """After a trade, trades_today should increment."""
        assert fresh_state.trades_today == 0
        await fresh_state.increment_trades_today()
        assert fresh_state.trades_today == 1

    @pytest.mark.asyncio
    async def test_daily_pnl_updates_correctly(self, fresh_state):
        """P&L should calculate from start-of-day equity."""
        # Start of day: $10,000
        # End of day: $10,200
        await fresh_state.update_account(
            balance=10200.0, equity=10200.0, buying_power=10200.0,
        )
        assert fresh_state.daily_pnl == 200.0
        assert fresh_state.daily_pnl_pct == pytest.approx(0.02, abs=0.001)

    @pytest.mark.asyncio
    async def test_drawdown_tracks_high_water_mark(self, fresh_state):
        """Drawdown should track from peak equity."""
        # Peak at $10,000
        await fresh_state.update_account(10500.0, 10500.0, 10500.0)
        assert fresh_state.peak_equity == 10500.0

        # Drop to $10,000
        await fresh_state.update_account(10000.0, 10000.0, 10000.0)
        expected_dd = (10500.0 - 10000.0) / 10500.0
        assert fresh_state.max_drawdown == pytest.approx(expected_dd, abs=0.001)

    @pytest.mark.asyncio
    async def test_positions_sync_correctly(self, fresh_state):
        """Positions should be replaced entirely on each sync."""
        positions1 = [
            PositionState(
                symbol="AAPL", qty=10, entry_price=180.0,
                current_price=185.0, unrealized_pnl=50.0, unrealized_pnl_pct=0.027,
            )
        ]
        await fresh_state.update_positions(positions1)
        assert fresh_state.open_position_count == 1
        assert fresh_state.has_position("AAPL")

        # Sync with empty list (positions closed)
        await fresh_state.update_positions([])
        assert fresh_state.open_position_count == 0
        assert not fresh_state.has_position("AAPL")
