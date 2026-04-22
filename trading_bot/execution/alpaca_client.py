"""
Cliente de Alpaca Markets para ejecución de órdenes y datos de mercado.

Soporta:
    - Bracket orders (entry + stop loss + take profit atómicos)
    - Multi-timeframe data fetch (5min, 15min, 1h)
    - Retry con backoff exponencial en TODAS las llamadas
    - Verificación de estado de órdenes
"""

from typing import Any, Dict

import pandas as pd
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.live import StockDataStream
from alpaca.data.requests import StockBarsRequest, StockLatestQuoteRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderClass, OrderSide, TimeInForce
from alpaca.trading.requests import (
    MarketOrderRequest,
    StopLossRequest,
    TakeProfitRequest,
)
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from ..config import constants as C
from ..config.exceptions import OrderExecutionError
from ..config.settings import settings


class AlpacaClient:
    """
    Cliente unificado para trading y datos de mercado en Alpaca.

    Todas las operaciones de red incluyen retry con backoff exponencial.
    Los métodos son sincónicos — usar asyncio.to_thread() desde código async.
    """

    def __init__(self) -> None:
        is_paper = settings.TRADING_MODE == "paper"
        self.trading_client = TradingClient(
            api_key=settings.ALPACA_API_KEY,
            secret_key=settings.ALPACA_SECRET_KEY,
            paper=is_paper,
        )
        self.data_client = StockHistoricalDataClient(
            api_key=settings.ALPACA_API_KEY,
            secret_key=settings.ALPACA_SECRET_KEY,
        )
        logger.info(f"Alpaca client initialized (paper={is_paper})")

    # ═══════════════════════════════════════
    # ACCOUNT & POSITIONS
    # ═══════════════════════════════════════

    @retry(wait=wait_exponential(min=1, max=10), stop=stop_after_attempt(3))
    def get_account_info(self) -> Any:
        """Retrieve current account information."""
        return self.trading_client.get_account()

    @retry(wait=wait_exponential(min=1, max=10), stop=stop_after_attempt(3))
    def get_positions(self) -> Any:
        """List all open positions."""
        return self.trading_client.get_all_positions()

    @retry(wait=wait_exponential(min=1, max=10), stop=stop_after_attempt(3))
    def close_position(self, symbol: str) -> Any:
        """Close an entire position for a given symbol."""
        logger.info(f"Closing full position for {symbol}", trade=True)
        return self.trading_client.close_position(symbol)

    # ═══════════════════════════════════════
    # ORDER EXECUTION
    # ═══════════════════════════════════════

    @retry(wait=wait_exponential(min=1, max=10), stop=stop_after_attempt(3))
    def submit_bracket_order(
        self,
        symbol: str,
        qty: int,
        side: OrderSide,
        stop_loss_price: float,
        take_profit_price: float,
    ) -> Any:
        """
        Submit a bracket order: entry + SL + TP as one atomic unit.

        The broker handles the OCO (one-cancels-other) logic server-side,
        so the SL and TP are guaranteed to be placed if the entry fills.

        Args:
            symbol: Ticker symbol.
            qty: Number of shares.
            side: BUY or SELL.
            stop_loss_price: Stop loss trigger price.
            take_profit_price: Take profit limit price.

        Returns:
            Alpaca Order object.

        Raises:
            OrderExecutionError: If the order submission fails.
        """
        order_data = MarketOrderRequest(
            symbol=symbol,
            qty=qty,
            side=side,
            time_in_force=TimeInForce.DAY,
            order_class=OrderClass.BRACKET,
            stop_loss=StopLossRequest(stop_price=round(stop_loss_price, 2)),
            take_profit=TakeProfitRequest(limit_price=round(take_profit_price, 2)),
        )

        logger.info(
            f"📤 Bracket Order: {side.value} {qty} {symbol} | "
            f"SL=${stop_loss_price:.2f} | TP=${take_profit_price:.2f}",
            trade=True,
        )

        try:
            order = self.trading_client.submit_order(order_data)
            logger.success(
                f"✅ Order accepted: ID={order.id}, Status={order.status}",
                trade=True,
            )
            return order
        except Exception as e:
            raise OrderExecutionError(
                ticker=symbol, side=side.value, reason=str(e),
            )

    @retry(wait=wait_exponential(min=1, max=10), stop=stop_after_attempt(3))
    def submit_notional_order(
        self,
        symbol: str,
        notional: float,
        side: OrderSide,
    ) -> Any:
        """
        Submit a market order using notional dollar value directly.
        Required for fractional shares where we cannot specify exact integers.
        """
        # Ensure notional is rounded to 2 decimal places to satisfy API
        notional = round(notional, 2)
        
        order_data = MarketOrderRequest(
            symbol=symbol,
            notional=notional,
            side=side,
            time_in_force=TimeInForce.DAY,
        )
        logger.info(f"📤 Notional Order: {side.value} ${notional} {symbol}", trade=True)
        try:
            return self.trading_client.submit_order(order_data)
        except Exception as e:
            raise OrderExecutionError(
                ticker=symbol, side=side.value, reason=str(e),
            )

    @retry(wait=wait_exponential(min=1, max=10), stop=stop_after_attempt(3))
    def submit_simple_order(
        self,
        symbol: str,
        qty: int,
        side: OrderSide,
    ) -> Any:
        """
        Submit a simple market order without brackets.

        Used for closing positions or simple entries.

        Args:
            symbol: Ticker symbol.
            qty: Number of shares.
            side: BUY or SELL.

        Returns:
            Alpaca Order object.
        """
        order_data = MarketOrderRequest(
            symbol=symbol,
            qty=qty,
            side=side,
            time_in_force=TimeInForce.DAY,
        )
        logger.info(f"📤 Simple Order: {side.value} {qty} {symbol}", trade=True)
        return self.trading_client.submit_order(order_data)

    @retry(wait=wait_exponential(min=1, max=10), stop=stop_after_attempt(3))
    def get_order_by_id(self, order_id: str) -> Any:
        """
        Check the status of an existing order.

        Args:
            order_id: Alpaca order ID string.

        Returns:
            Order object with current status.
        """
        return self.trading_client.get_order_by_id(order_id)

    @retry(wait=wait_exponential(min=1, max=10), stop=stop_after_attempt(3))
    def get_asset(self, symbol: str) -> Any:
        """
        Get asset details to check if fractional shares are supported.

        Args:
            symbol: Ticker symbol.

        Returns:
            Asset object with fractionable flag.
        """
        return self.trading_client.get_asset(symbol)

    # ═══════════════════════════════════════
    # MARKET DATA
    # ═══════════════════════════════════════

    @retry(wait=wait_exponential(min=1, max=10), stop=stop_after_attempt(3))
    def get_historical_bars(
        self,
        symbol: str,
        timeframe: TimeFrame,
        limit: int = C.DEFAULT_BAR_LIMIT,
    ) -> pd.DataFrame:
        """
        Fetch historical bars and return as a pandas DataFrame.

        Args:
            symbol: Ticker symbol.
            timeframe: Bar timeframe (e.g., TimeFrame.Hour).
            limit: Maximum number of bars to fetch.

        Returns:
            DataFrame with OHLCV data, or empty DataFrame on error.
        """
        try:
            request = StockBarsRequest(
                symbol_or_symbols=symbol,
                timeframe=timeframe,
                limit=limit,
            )
            bars = self.data_client.get_stock_bars(request)
            df = bars.df.reset_index()
            return df
        except Exception as e:
            logger.error(f"Error fetching bars for {symbol} ({timeframe}): {e}")
            return pd.DataFrame()

    @retry(wait=wait_exponential(min=1, max=10), stop=stop_after_attempt(3))
    def get_latest_quote(self, symbol: str) -> Any:
        """
        Get the latest quote for a symbol.

        Args:
            symbol: Ticker symbol.

        Returns:
            Alpaca quote object.
        """
        request = StockLatestQuoteRequest(symbol_or_symbols=symbol)
        return self.data_client.get_stock_latest_quote(request)

    @retry(wait=wait_exponential(min=1, max=10), stop=stop_after_attempt(3))
    def get_clock(self) -> Any:
        """Fetch market clock status from Alpaca API."""
        try:
            return self.trading_client.get_clock()
        except Exception as e:
            logger.error(f"Error checking market clock: {e}")
            raise

    def get_multi_timeframe_bars(
        self,
        symbol: str,
        limit: int = C.DEFAULT_BAR_LIMIT,
    ) -> Dict[str, pd.DataFrame]:
        """
        Fetch bars for multiple timeframes (5min, 15min, 1h).

        Args:
            symbol: Ticker symbol.
            limit: Number of bars per timeframe.

        Returns:
            Dict mapping timeframe label to DataFrame.
        """
        timeframe_configs = [
            ("5min", TimeFrame(5, TimeFrameUnit.Minute)),
            ("15min", TimeFrame(15, TimeFrameUnit.Minute)),
            ("1h", TimeFrame.Hour),
        ]

        results: Dict[str, pd.DataFrame] = {}
        for label, tf in timeframe_configs:
            try:
                results[label] = self.get_historical_bars(symbol, tf, limit)
            except Exception as e:
                logger.warning(f"Failed to get {label} data for {symbol}: {e}")
                results[label] = pd.DataFrame()

        return results

    def create_data_stream(self) -> StockDataStream:
        """
        Create a new StockDataStream instance for WebSocket connections.

        Returns:
            Configured StockDataStream ready for subscriptions.
        """
        return StockDataStream(
            api_key=settings.ALPACA_API_KEY,
            secret_key=settings.ALPACA_SECRET_KEY,
        )
