"""
Cálculo de indicadores técnicos y sistema de scoring de señales.

Usa pandas-ta para indicadores estandarizados de la industria.
Todos los períodos y pesos están centralizados en constants.py.
Protección completa contra NaN en todos los cálculos de scoring.
"""

from typing import Optional

import pandas as pd
import pandas_ta as ta
from loguru import logger

from ..config import constants as C


class TechnicalAnalysis:
    """Calcula indicadores técnicos y genera scores de confluencia."""

    @staticmethod
    def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
        """
        Calcula todos los indicadores técnicos sobre un DataFrame OHLCV.

        Args:
            df: DataFrame con columnas [timestamp, open, high, low, close, volume].
                Debe tener al menos MIN_BARS_FOR_INDICATORS filas.

        Returns:
            DataFrame enriquecido con columnas de indicadores.
            Retorna el DataFrame original si no hay suficientes datos.
        """
        if df.empty or len(df) < C.MIN_BARS_FOR_INDICATORS:
            logger.warning(
                f"DataFrame insuficiente ({len(df)} barras) para indicadores "
                f"(mínimo: {C.MIN_BARS_FOR_INDICATORS})"
            )
            return df

        # Normalizar columnas a minúscula para pandas-ta
        df.columns = [c.lower() for c in df.columns]

        df = TechnicalAnalysis._add_trend_indicators(df)
        df = TechnicalAnalysis._add_momentum_indicators(df)
        df = TechnicalAnalysis._add_volatility_indicators(df)
        df = TechnicalAnalysis._add_volume_indicators(df)

        return df

    @staticmethod
    def _add_trend_indicators(df: pd.DataFrame) -> pd.DataFrame:
        """Add EMA stack and SuperTrend indicators."""
        df["EMA_9"] = ta.ema(df["close"], length=C.EMA_FAST_PERIOD)
        df["EMA_21"] = ta.ema(df["close"], length=C.EMA_MID_PERIOD)
        df["EMA_50"] = ta.ema(df["close"], length=C.EMA_SLOW_PERIOD)
        df["EMA_200"] = ta.ema(df["close"], length=C.EMA_TREND_PERIOD)

        st = ta.supertrend(
            df["high"], df["low"], df["close"],
            length=C.SUPERTREND_PERIOD,
            multiplier=C.SUPERTREND_MULTIPLIER,
        )
        if st is not None:
            st_col = f"SUPERT_{C.SUPERTREND_PERIOD}_{C.SUPERTREND_MULTIPLIER}"
            std_col = f"SUPERTd_{C.SUPERTREND_PERIOD}_{C.SUPERTREND_MULTIPLIER}"
            df["SUPERT"] = st.get(st_col)
            df["SUPERT_DIR"] = st.get(std_col)

        return df

    @staticmethod
    def _add_momentum_indicators(df: pd.DataFrame) -> pd.DataFrame:
        """Add RSI and MACD indicators."""
        df["RSI"] = ta.rsi(df["close"], length=C.RSI_PERIOD)

        macd = ta.macd(
            df["close"],
            fast=C.MACD_FAST,
            slow=C.MACD_SLOW,
            signal=C.MACD_SIGNAL,
        )
        if macd is not None:
            prefix = f"{C.MACD_FAST}_{C.MACD_SLOW}_{C.MACD_SIGNAL}"
            df["MACD"] = macd.get(f"MACD_{prefix}")
            df["MACD_S"] = macd.get(f"MACDs_{prefix}")
            df["MACD_H"] = macd.get(f"MACDh_{prefix}")

        return df

    @staticmethod
    def _add_volatility_indicators(df: pd.DataFrame) -> pd.DataFrame:
        """Add ATR and Bollinger Bands indicators."""
        df["ATR"] = ta.atr(
            df["high"], df["low"], df["close"],
            length=C.ATR_PERIOD,
        )

        bbands = ta.bbands(
            df["close"],
            length=C.BBANDS_PERIOD,
            std=C.BBANDS_STD,
        )
        if bbands is not None:
            suffix = f"{C.BBANDS_PERIOD}_{C.BBANDS_STD}"
            df["BBL"] = bbands.get(f"BBL_{suffix}")
            df["BBM"] = bbands.get(f"BBM_{suffix}")
            df["BBU"] = bbands.get(f"BBU_{suffix}")

        return df

    @staticmethod
    def _add_volume_indicators(df: pd.DataFrame) -> pd.DataFrame:
        """Add VWAP and relative volume indicators."""
        df["VWAP"] = ta.vwap(df["high"], df["low"], df["close"], df["volume"])
        df["VOL_SMA20"] = ta.sma(df["volume"], length=C.VOLUME_SMA_PERIOD)
        df["REL_VOL"] = df["volume"] / df["VOL_SMA20"].replace(0, float("nan"))
        return df

    @staticmethod
    def get_signal_score(df: pd.DataFrame) -> int:
        """
        Genera un score de confluencia técnica de 0 a 100.

        Criteria (all bullish):
            - EMA Stack (9 > 21 > 50 > 200): +20pts
            - RSI en zona favorable (40-65): +15pts
            - MACD Bullish Cross: +20pts
            - Precio sobre VWAP: +15pts
            - Volumen relativo > 1.5x: +10pts
            - SuperTrend alcista: +20pts

        Args:
            df: DataFrame con indicadores ya calculados.

        Returns:
            Score entero de 0 a 100.
        """
        if df.empty or len(df) < 2:
            return 0

        last = df.iloc[-1]
        prev = df.iloc[-2]
        score = 0

        # EMA Stack Bullish (+20)
        score += TechnicalAnalysis._score_ema_stack(last)

        # RSI favorable zone (+15)
        score += TechnicalAnalysis._score_rsi(last)

        # MACD Bullish Cross (+20)
        score += TechnicalAnalysis._score_macd_cross(last, prev)

        # Price above VWAP (+15)
        score += TechnicalAnalysis._score_vwap(last)

        # Relative volume above threshold (+10)
        score += TechnicalAnalysis._score_volume(last)

        # SuperTrend bullish (+20)
        score += TechnicalAnalysis._score_supertrend(last)

        return score

    # ═══════════════════════════════════════
    # SCORING HELPERS (NaN-safe)
    # ═══════════════════════════════════════

    @staticmethod
    def _safe_get(row: pd.Series, col: str) -> Optional[float]:
        """Safely get a numeric value, returning None for NaN or missing."""
        val = row.get(col)
        if val is not None and pd.notna(val):
            return float(val)
        return None

    @staticmethod
    def _score_ema_stack(last: pd.Series) -> int:
        """Score EMA stack alignment (9 > 21 > 50 > 200)."""
        vals = [
            TechnicalAnalysis._safe_get(last, col)
            for col in ["EMA_9", "EMA_21", "EMA_50", "EMA_200"]
        ]
        if all(v is not None for v in vals):
            if vals[0] > vals[1] > vals[2] > vals[3]:
                return C.SCORE_EMA_STACK
        return 0

    @staticmethod
    def _score_rsi(last: pd.Series) -> int:
        """Score RSI in favorable bullish zone."""
        rsi = TechnicalAnalysis._safe_get(last, "RSI")
        if rsi is not None and C.RSI_BULLISH_MIN <= rsi <= C.RSI_BULLISH_MAX:
            return C.SCORE_RSI_CONTEXT
        return 0

    @staticmethod
    def _score_macd_cross(last: pd.Series, prev: pd.Series) -> int:
        """Score MACD bullish crossover (MACD crosses above signal)."""
        macd_now = TechnicalAnalysis._safe_get(last, "MACD")
        signal_now = TechnicalAnalysis._safe_get(last, "MACD_S")
        macd_prev = TechnicalAnalysis._safe_get(prev, "MACD")
        signal_prev = TechnicalAnalysis._safe_get(prev, "MACD_S")

        if all(v is not None for v in [macd_now, signal_now, macd_prev, signal_prev]):
            if macd_prev < signal_prev and macd_now > signal_now:
                return C.SCORE_MACD_CROSS
        return 0

    @staticmethod
    def _score_vwap(last: pd.Series) -> int:
        """Score price position relative to VWAP."""
        close = TechnicalAnalysis._safe_get(last, "close")
        vwap = TechnicalAnalysis._safe_get(last, "VWAP")
        if close is not None and vwap is not None and close > vwap:
            return C.SCORE_ABOVE_VWAP
        return 0

    @staticmethod
    def _score_volume(last: pd.Series) -> int:
        """Score relative volume above threshold."""
        rel_vol = TechnicalAnalysis._safe_get(last, "REL_VOL")
        if rel_vol is not None and rel_vol > C.RELATIVE_VOLUME_THRESHOLD:
            return C.SCORE_RELATIVE_VOLUME
        return 0

    @staticmethod
    def _score_supertrend(last: pd.Series) -> int:
        """Score SuperTrend direction."""
        st_dir = TechnicalAnalysis._safe_get(last, "SUPERT_DIR")
        if st_dir is not None and st_dir == 1:
            return C.SCORE_SUPERTREND
        return 0
