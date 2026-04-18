from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, GetOrdersRequest
from alpaca.trading.enums import OrderSide, TimeInForce, QueryOrderStatus
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, StockLatestQuoteRequest
from alpaca.data.timeframe import TimeFrame
from tenacity import retry, wait_exponential, stop_after_attempt
from loguru import logger
from ..config.settings import settings
from typing import Optional, List
import pandas as pd

class AlpacaClient:
    def __init__(self):
        self.trading_client = TradingClient(
            api_key=settings.ALPACA_API_KEY,
            secret_key=settings.ALPACA_SECRET_KEY,
            paper=(settings.TRADING_MODE == "paper")
        )
        self.data_client = StockHistoricalDataClient(
            api_key=settings.ALPACA_API_KEY,
            secret_key=settings.ALPACA_SECRET_KEY
        )

    @retry(wait=wait_exponential(min=1, max=10), stop=stop_after_attempt(3))
    def get_account_info(self):
        return self.trading_client.get_account()

    @retry(wait=wait_exponential(min=1, max=10), stop=stop_after_attempt(3))
    def get_positions(self):
        return self.trading_client.get_all_positions()

    @retry(wait=wait_exponential(min=1, max=10), stop=stop_after_attempt(3))
    def submit_order(self, symbol: str, qty: float, side: OrderSide):
        order_data = MarketOrderRequest(
            symbol=symbol,
            qty=qty,
            side=side,
            time_in_force=TimeInForce.GTC
        )
        logger.info(f"Enviando orden {side} para {symbol} (Qty: {qty})", trade=True)
        return self.trading_client.submit_order(order_data)

    def get_historical_bars(self, symbol: str, timeframe: TimeFrame, limit: int = 200) -> pd.DataFrame:
        """Obtiene barras históricas y las devuelve como DataFrame"""
        try:
            request = StockBarsRequest(
                symbol_or_symbols=symbol,
                timeframe=timeframe,
                limit=limit
            )
            bars = self.data_client.get_stock_bars(request)
            df = bars.df.reset_index()
            # Renombrar columnas para consistencia si es necesario
            return df
        except Exception as e:
            logger.error(f"Error obteniendo barras para {symbol}: {e}")
            return pd.DataFrame()

    def get_latest_quote(self, symbol: str):
        request = StockLatestQuoteRequest(symbol_or_symbols=symbol)
        return self.data_client.get_stock_latest_quote(request)
