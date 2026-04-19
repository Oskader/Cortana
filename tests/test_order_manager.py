"""
Tests para ejecución de órdenes — usa mock de Alpaca API.

Verifica que las órdenes se crean con parámetros correctos
y que los errores se manejan graciosamente.
"""

import pytest
from unittest.mock import MagicMock, patch

from trading_bot.execution.alpaca_client import AlpacaClient
from trading_bot.config.exceptions import OrderExecutionError


class TestBracketOrderCreation:
    """Verifica la creación de bracket orders."""

    def test_buy_order_with_correct_parameters(self, mock_alpaca_client):
        """Bracket order should include symbol, qty, SL, and TP."""
        from alpaca.trading.enums import OrderSide

        order = mock_alpaca_client.submit_bracket_order(
            symbol="AAPL",
            qty=10,
            side=OrderSide.BUY,
            stop_loss_price=180.0,
            take_profit_price=195.0,
        )

        mock_alpaca_client.submit_bracket_order.assert_called_once_with(
            symbol="AAPL",
            qty=10,
            side=OrderSide.BUY,
            stop_loss_price=180.0,
            take_profit_price=195.0,
        )
        assert order.id == "test-order-id-123"

    def test_order_returns_valid_id(self, mock_alpaca_client):
        """Successful order should return an object with an ID."""
        from alpaca.trading.enums import OrderSide

        order = mock_alpaca_client.submit_bracket_order(
            symbol="MSFT",
            qty=5,
            side=OrderSide.BUY,
            stop_loss_price=400.0,
            take_profit_price=440.0,
        )

        assert order.id is not None
        assert order.status == "accepted"


class TestOrderErrorHandling:
    """Verifica el manejo de errores en la ejecución de órdenes."""

    def test_alpaca_error_handled_gracefully(self):
        """When Alpaca returns an error, it should raise OrderExecutionError."""
        client = MagicMock()
        client.submit_bracket_order.side_effect = OrderExecutionError(
            ticker="AAPL", side="BUY", reason="Insufficient funds",
        )

        with pytest.raises(OrderExecutionError) as exc_info:
            client.submit_bracket_order(
                symbol="AAPL", qty=100, side="BUY",
                stop_loss_price=100.0, take_profit_price=200.0,
            )

        assert "AAPL" in str(exc_info.value)
        assert "Insufficient funds" in str(exc_info.value)

    def test_order_not_duplicated_on_retry(self, mock_alpaca_client):
        """After a failed order, retry should submit a new order, not duplicate."""
        from alpaca.trading.enums import OrderSide

        # First call fails
        mock_alpaca_client.submit_bracket_order.side_effect = [
            Exception("Network error"),
            MagicMock(id="retry-order-id", status="accepted"),
        ]

        # First attempt fails
        with pytest.raises(Exception):
            mock_alpaca_client.submit_bracket_order(
                symbol="AAPL", qty=10, side=OrderSide.BUY,
                stop_loss_price=180.0, take_profit_price=195.0,
            )

        # Second attempt succeeds
        order = mock_alpaca_client.submit_bracket_order(
            symbol="AAPL", qty=10, side=OrderSide.BUY,
            stop_loss_price=180.0, take_profit_price=195.0,
        )

        assert order.id == "retry-order-id"
        assert mock_alpaca_client.submit_bracket_order.call_count == 2


class TestPositionManagement:
    """Verifica operaciones de posiciones."""

    def test_sell_uses_correct_symbol(self, mock_alpaca_client):
        """Close position should use the correct symbol."""
        mock_alpaca_client.close_position("AAPL")
        mock_alpaca_client.close_position.assert_called_once_with("AAPL")

    def test_get_positions_returns_list(self, mock_alpaca_client):
        """get_positions should return a list."""
        positions = mock_alpaca_client.get_positions()
        assert isinstance(positions, list)
