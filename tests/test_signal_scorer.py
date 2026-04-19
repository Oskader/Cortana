"""
Tests para el Signal Scoring System — verifica que el scoring
es determinístico y produce resultados correctos para setups conocidos.
"""

import pytest
import pandas as pd
import numpy as np

from trading_bot.market.indicators import TechnicalAnalysis
from trading_bot.config import constants as C


class TestSignalScoring:
    """Verifica el sistema de scoring de 0-100 puntos."""

    def test_full_bullish_confluence_above_70(self, sample_ohlcv_df):
        """
        A fully bullish setup (all indicators aligned) should
        produce a score >= 70 (strong signal threshold).
        """
        ta = TechnicalAnalysis()

        # Create a DataFrame that simulates a perfectly bullish setup
        df = self._create_bullish_df()
        score = ta.get_signal_score(df)

        assert score >= C.SCORE_STRONG_SIGNAL, (
            f"Full confluence should score >= {C.SCORE_STRONG_SIGNAL}, got {score}"
        )

    def test_no_signals_score_zero(self):
        """An empty DataFrame should score 0."""
        ta = TechnicalAnalysis()
        score = ta.get_signal_score(pd.DataFrame())
        assert score == 0

    def test_single_bar_scores_zero(self):
        """A DataFrame with only 1 row should score 0 (needs prev bar)."""
        ta = TechnicalAnalysis()
        df = pd.DataFrame({"close": [100.0]})
        score = ta.get_signal_score(df)
        assert score == 0

    def test_scoring_is_deterministic(self, sample_ohlcv_df):
        """Same input should always produce same output."""
        ta = TechnicalAnalysis()
        df = ta.calculate_indicators(sample_ohlcv_df)

        score1 = ta.get_signal_score(df)
        score2 = ta.get_signal_score(df)
        score3 = ta.get_signal_score(df)

        assert score1 == score2 == score3

    def test_nan_indicators_dont_crash(self):
        """
        DataFrame with NaN values in indicator columns should
        produce a valid score without crashing.
        """
        ta = TechnicalAnalysis()
        df = pd.DataFrame({
            "close": [100.0, 101.0],
            "EMA_9": [float("nan"), float("nan")],
            "EMA_21": [100.0, 100.5],
            "EMA_50": [99.0, 99.5],
            "EMA_200": [98.0, 98.5],
            "RSI": [float("nan"), float("nan")],
            "MACD": [0.1, 0.2],
            "MACD_S": [0.15, 0.1],
            "VWAP": [99.5, 100.5],
            "REL_VOL": [float("nan"), float("nan")],
            "SUPERT_DIR": [1, 1],
        })

        # Should not raise, should return valid int
        score = ta.get_signal_score(df)
        assert isinstance(score, int)
        assert 0 <= score <= 100

    def test_ema_stack_scoring(self):
        """EMA stack (9>21>50>200) should add 20 points."""
        df = pd.DataFrame({
            "close": [100.0, 101.0],
            "EMA_9": [104.0, 104.0],
            "EMA_21": [103.0, 103.0],
            "EMA_50": [102.0, 102.0],
            "EMA_200": [101.0, 101.0],
            "RSI": [30.0, 30.0],  # Out of range
            "MACD": [0.1, 0.1],
            "MACD_S": [0.1, 0.1],  # No cross
            "VWAP": [110.0, 110.0],  # Below VWAP
            "REL_VOL": [0.5, 0.5],  # Low volume
            "SUPERT_DIR": [-1, -1],  # Bearish
        })
        ta = TechnicalAnalysis()
        score = ta.get_signal_score(df)
        assert score == C.SCORE_EMA_STACK  # Only EMA stack contributes

    def test_rsi_scoring(self):
        """RSI in 40-65 range should add 15 points."""
        df = pd.DataFrame({
            "close": [100.0, 101.0],
            "EMA_9": [100.0, 100.0],
            "EMA_21": [101.0, 101.0],  # Wrong order
            "EMA_50": [102.0, 102.0],
            "EMA_200": [103.0, 103.0],
            "RSI": [55.0, 55.0],  # In range
            "MACD": [0.1, 0.1],
            "MACD_S": [0.1, 0.1],
            "VWAP": [110.0, 110.0],
            "REL_VOL": [0.5, 0.5],
            "SUPERT_DIR": [-1, -1],
        })
        ta = TechnicalAnalysis()
        score = ta.get_signal_score(df)
        assert score == C.SCORE_RSI_CONTEXT

    def test_indicators_calculated_on_real_data(self, sample_ohlcv_df):
        """Indicators should calculate without errors on realistic data."""
        ta = TechnicalAnalysis()
        df = ta.calculate_indicators(sample_ohlcv_df)

        # Check key columns exist
        for col in ["EMA_9", "EMA_21", "RSI", "MACD", "ATR", "VWAP"]:
            assert col in df.columns, f"Missing indicator column: {col}"

        # Check no all-NaN columns (at least some valid values)
        for col in ["EMA_9", "RSI", "MACD"]:
            assert df[col].notna().any(), f"Column {col} is all NaN"

    # ═══════════════════════════════════════
    # HELPER METHODS
    # ═══════════════════════════════════════

    @staticmethod
    def _create_bullish_df() -> pd.DataFrame:
        """Create a DataFrame that simulates a perfect bullish setup."""
        return pd.DataFrame({
            "close": [185.0, 186.0],
            "EMA_9": [185.5, 185.8],
            "EMA_21": [184.5, 184.8],
            "EMA_50": [183.0, 183.3],
            "EMA_200": [180.0, 180.2],
            "RSI": [55.0, 58.0],
            "MACD": [-0.1, 0.3],  # Crosses above
            "MACD_S": [0.1, 0.1],  # Signal stays flat
            "VWAP": [184.0, 184.5],  # Below close
            "REL_VOL": [2.0, 2.0],  # Above 1.5 threshold
            "SUPERT_DIR": [1, 1],
        })
