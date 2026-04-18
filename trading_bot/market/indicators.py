import pandas as pd
import pandas_ta as ta
from loguru import logger
from typing import Optional

class TechnicalAnalysis:
    @staticmethod
    def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
        """
        Calcular indicadores técnicos usando pandas-ta.
        Se espera un DataFrame con columnas: [timestamp, open, high, low, close, volume]
        """
        if df.empty or len(df) < 50:
            logger.warning("DataFrame insuficiente para calcular indicadores")
            return df

        # Asegurar que las columnas sean minúsculas para pandas-ta
        df.columns = [c.lower() for c in df.columns]

        # Tendencia
        df["EMA_9"] = ta.ema(df["close"], length=9)
        df["EMA_21"] = ta.ema(df["close"], length=21)
        df["EMA_50"] = ta.ema(df["close"], length=50)
        df["EMA_200"] = ta.ema(df["close"], length=200)
        
        # SuperTrend
        st = ta.supertrend(df["high"], df["low"], df["close"], length=10, multiplier=3)
        if st is not None:
            df["SUPERT"] = st["SUPERT_10_3.0"]
            df["SUPERT_DIR"] = st["SUPERTd_10_3.0"]

        # Momentum
        df["RSI"] = ta.rsi(df["close"], length=14)
        
        macd = ta.macd(df["close"], fast=12, slow=26, signal=9)
        if macd is not None:
            df["MACD"] = macd["MACD_12_26_9"]
            df["MACD_S"] = macd["MACDs_12_26_9"]
            df["MACD_H"] = macd["MACDh_12_26_9"]

        # Volatilidad
        df["ATR"] = ta.atr(df["high"], df["low"], df["close"], length=14)
        
        bbands = ta.bbands(df["close"], length=20, std=2)
        if bbands is not None:
            df["BBL"] = bbands["BBL_20_2.0"]
            df["BBM"] = bbands["BBM_20_2.0"]
            df["BBU"] = bbands["BBU_20_2.0"]

        # Volumen
        df["VWAP"] = ta.vwap(df["high"], df["low"], df["close"], df["volume"])
        df["VOL_SMA20"] = ta.sma(df["volume"], length=20)
        df["REL_VOL"] = df["volume"] / df["VOL_SMA20"]

        return df

    @staticmethod
    def get_signal_score(df: pd.DataFrame) -> int:
        """
        Implementa el scoring system de 0-100 sugerido.
        """
        if df.empty: return 0
        
        last = df.iloc[-1]
        prev = df.iloc[-2]
        score = 0

        # EMA Stack (+20)
        if last["EMA_9"] > last["EMA_21"] > last["EMA_50"] > last["EMA_200"]:
            score += 20
        
        # RSI Context (+15)
        if 40 <= last["RSI"] <= 65:
            score += 15
        
        # MACD Bullish Cross (+20)
        if prev["MACD"] < prev["MACD_S"] and last["MACD"] > last["MACD_S"]:
            score += 20
        
        # Above VWAP (+15)
        if last["close"] > last["VWAP"]:
            score += 15
        
        # Relative Volume (+10)
        if last["REL_VOL"] > 1.5:
            score += 10
            
        # SuperTrend Confirmation (+20)
        if last["SUPERT_DIR"] == 1:
            score += 20
            
        return score
