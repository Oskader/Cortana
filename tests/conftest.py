"""
Fixtures y mocks compartidos para el test suite de Cortana Bot.

Provee:
    - Portfolio mock con $10,000 de balance
    - OHLCV data realista para AAPL (100 barras de 1h)
    - Mock de AlpacaClient (sin llamadas reales)
    - Mock de GroqClient con respuesta configurable
    - Settings de prueba con valores seguros
"""

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pandas as pd
import pytest
import pytest_asyncio

from trading_bot.brain.groq_agent import GroqTradeSignal
from trading_bot.config import constants as C
from trading_bot.core.state import GlobalState, PositionState


# ═══════════════════════════════════════
# FIXTURES — Market Data
# ═══════════════════════════════════════

@pytest.fixture
def sample_ohlcv_df() -> pd.DataFrame:
    """
    Generate realistic OHLCV data for AAPL (100 bars, 1h timeframe).
    Simulates a mild uptrend with normal volatility.
    """
    np.random.seed(42)
    n_bars = 100
    base_price = 180.0

    # Generate random walk for close prices
    returns = np.random.normal(0.0002, 0.005, n_bars)
    close_prices = base_price * np.cumprod(1 + returns)

    # Generate OHLC from close
    high_prices = close_prices * (1 + np.abs(np.random.normal(0, 0.003, n_bars)))
    low_prices = close_prices * (1 - np.abs(np.random.normal(0, 0.003, n_bars)))
    open_prices = np.roll(close_prices, 1)
    open_prices[0] = base_price

    # Volume with some variation
    volumes = np.random.randint(500_000, 2_000_000, n_bars)

    timestamps = [
        datetime(2026, 4, 1, 9, 30) + timedelta(hours=i)
        for i in range(n_bars)
    ]

    df = pd.DataFrame({
        "timestamp": timestamps,
        "open": open_prices,
        "high": high_prices,
        "low": low_prices,
        "close": close_prices,
        "volume": volumes,
        "symbol": "AAPL",
    })

    return df


@pytest.fixture
def sample_indicators_dict() -> dict:
    """Sample indicator values for a bullish setup."""
    return {
        "close": 185.50,
        "EMA_9": 185.20,
        "EMA_21": 184.80,
        "EMA_50": 183.50,
        "EMA_200": 180.00,
        "RSI": 55.0,
        "MACD": 0.45,
        "MACD_S": 0.30,
        "MACD_H": 0.15,
        "ATR": 2.50,
        "BBU": 188.00,
        "BBM": 184.00,
        "BBL": 180.00,
        "VWAP": 184.50,
        "REL_VOL": 1.8,
        "SUPERT_DIR": 1,
    }


# ═══════════════════════════════════════
# FIXTURES — Trade Signals
# ═══════════════════════════════════════

@pytest.fixture
def valid_buy_signal() -> GroqTradeSignal:
    """A valid BUY signal that should pass all risk checks."""
    return GroqTradeSignal(
        action="BUY",
        ticker="AAPL",
        confidence=0.82,
        reasoning="Strong EMA stack alignment with MACD bullish crossover and above-average volume confirming the trend.",
        entry_price_target=185.50,
        stop_loss=182.00,
        take_profit=192.00,
        time_horizon="intraday",
        risk_reward_ratio=1.86,
        invalidation_condition="Price closes below EMA 50 at 183.50",
    )


@pytest.fixture
def hold_signal() -> GroqTradeSignal:
    """A HOLD signal that should not trigger any trade."""
    return GroqTradeSignal(
        action="HOLD",
        ticker="AAPL",
        confidence=0.3,
        reasoning="Mixed signals — RSI divergence with price action, waiting for confirmation.",
        entry_price_target=185.50,
        stop_loss=182.00,
        take_profit=192.00,
        time_horizon="intraday",
        risk_reward_ratio=1.86,
        invalidation_condition="N/A",
    )


@pytest.fixture
def low_confidence_signal() -> GroqTradeSignal:
    """A signal with confidence below the minimum threshold."""
    return GroqTradeSignal(
        action="BUY",
        ticker="MSFT",
        confidence=0.50,
        reasoning="Weak setup with minimal confluence between indicators.",
        entry_price_target=420.00,
        stop_loss=415.00,
        take_profit=430.00,
        time_horizon="intraday",
        risk_reward_ratio=2.0,
        invalidation_condition="Price below VWAP",
    )


@pytest.fixture
def invalid_stop_loss_signal_data() -> dict:
    """Raw dict where stop_loss > entry_price (invalid for BUY)."""
    return {
        "action": "BUY",
        "ticker": "TSLA",
        "confidence": 0.75,
        "reasoning": "Bullish breakout pattern with volume confirmation on the daily chart.",
        "entry_price_target": 250.00,
        "stop_loss": 260.00,  # INVALID: above entry
        "take_profit": 280.00,
        "time_horizon": "swing",
        "risk_reward_ratio": 3.0,
        "invalidation_condition": "Gap down below support",
    }


# ═══════════════════════════════════════
# FIXTURES — Bot State
# ═══════════════════════════════════════

@pytest.fixture
def fresh_state() -> GlobalState:
    """A fresh GlobalState with $10,000 portfolio."""
    state = GlobalState()
    state.balance = 10000.0
    state.equity = 10000.0
    state.buying_power = 10000.0
    state.peak_equity = 10000.0
    state._start_of_day_equity = 10000.0
    state.is_running = True
    state.market_regime = C.REGIME_TRENDING_UP
    return state


@pytest.fixture
def state_with_positions() -> GlobalState:
    """A state with 5 open positions (max reached)."""
    state = GlobalState()
    state.balance = 5000.0
    state.equity = 10000.0
    state.buying_power = 5000.0
    state.peak_equity = 10500.0
    state._start_of_day_equity = 10200.0
    state.is_running = True

    positions = {}
    for sym in ["AAPL", "MSFT", "GOOGL", "NVDA", "META"]:
        positions[sym] = PositionState(
            symbol=sym,
            qty=10,
            entry_price=100.0,
            current_price=102.0,
            unrealized_pnl=20.0,
            unrealized_pnl_pct=0.02,
        )
    state.positions = positions
    return state


@pytest.fixture
def state_with_daily_loss() -> GlobalState:
    """A state where daily loss limit has been hit (-2.1%)."""
    state = GlobalState()
    state.balance = 9790.0
    state.equity = 9790.0
    state.buying_power = 9790.0
    state.peak_equity = 10000.0
    state._start_of_day_equity = 10000.0
    state.daily_pnl = -210.0
    state.daily_pnl_pct = -0.021  # -2.1%, exceeds -2% limit
    state.is_running = True
    return state


# ═══════════════════════════════════════
# FIXTURES — Mocks
# ═══════════════════════════════════════

@pytest.fixture
def mock_alpaca_client():
    """Mock AlpacaClient that doesn't make real API calls."""
    client = MagicMock()

    # Account info
    account = MagicMock()
    account.cash = "10000.00"
    account.portfolio_value = "10000.00"
    account.buying_power = "10000.00"
    client.get_account_info.return_value = account

    # Positions (empty)
    client.get_positions.return_value = []

    # Orders
    order = MagicMock()
    order.id = "test-order-id-123"
    order.status = "accepted"
    client.submit_bracket_order.return_value = order
    client.submit_simple_order.return_value = order

    return client


@pytest.fixture
def mock_groq_buy_response() -> dict:
    """Mock Groq response for a BUY signal."""
    return {
        "action": "BUY",
        "ticker": "AAPL",
        "confidence": 0.82,
        "reasoning": "Strong bullish setup with EMA alignment and MACD crossover",
        "entry_price_target": 185.50,
        "stop_loss": 182.00,
        "take_profit": 192.00,
        "time_horizon": "intraday",
        "risk_reward_ratio": 1.86,
        "invalidation_condition": "Close below EMA50",
    }


@pytest.fixture
def mock_groq_hold_response() -> dict:
    """Mock Groq response for a HOLD signal."""
    return {
        "action": "HOLD",
        "ticker": "AAPL",
        "confidence": 0.3,
        "reasoning": "No clear setup — mixed signals across timeframes",
        "entry_price_target": 185.50,
        "stop_loss": 182.00,
        "take_profit": 192.00,
        "time_horizon": "intraday",
        "risk_reward_ratio": 1.0,
        "invalidation_condition": "N/A",
    }
