"""
Screener de mercado: detecta régimen de mercado y filtra candidatos.

Usa yfinance para datos de SPY/VIX (régimen) y screening de universo.
Todas las llamadas se ejecutan via asyncio.to_thread() desde el engine.
"""

from typing import List

import yfinance as yf
from loguru import logger

from ..config import constants as C
from ..config.settings import settings


class Screener:
    """
    Detecta régimen de mercado y filtra acciones con alto volumen relativo.

    Métodos principales (todos sincónicos, usar con asyncio.to_thread):
        - get_market_regime(): SPY + VIX → régimen actual
        - scan_top_candidates(): universo → top 10 por volumen relativo
    """

    def __init__(self) -> None:
        self.base_universe: List[str] = [
            "AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "NVDA",
            "BRK-B", "JPM", "V", "UNH", "MA", "PG", "HD", "DIS",
            "PYPL", "BAC", "VZ", "ADBE", "CMCSA", "NFLX", "KO",
            "PEP", "INTC", "CSCO", "AVGO", "COST", "TMO", "PFE", "ABT",
        ]

    def get_market_regime(self) -> str:
        """
        Determina el régimen de mercado usando SPY y VIX.

        Logic:
            - VIX > 25 → HIGH_VOLATILITY (reduce position sizes)
            - SPY > SMA50 > SMA200 → TRENDING_UP
            - SPY < SMA50 < SMA200 → TRENDING_DOWN
            - Otherwise → RANGING

        Returns:
            One of the REGIME_* constants.
        """
        try:
            spy_regime = self._analyze_spy_trend()
            vix_level = self._get_vix_level()

            if vix_level > C.VIX_HIGH_THRESHOLD:
                logger.info(f"VIX={vix_level:.1f} (HIGH) → HIGH_VOLATILITY regime")
                return C.REGIME_HIGH_VOLATILITY

            logger.info(f"VIX={vix_level:.1f}, SPY trend={spy_regime}")
            return spy_regime

        except Exception as e:
            logger.error(f"Error detectando régimen de mercado: {e}")
            return C.REGIME_NEUTRAL

    def _analyze_spy_trend(self) -> str:
        """Analyze SPY price relative to its moving averages."""
        spy = yf.Ticker("SPY")
        hist = spy.history(period=C.SPY_HISTORY_PERIOD)

        if hist.empty or len(hist) < C.SPY_SMA_LONG:
            return C.REGIME_NEUTRAL

        last_close = float(hist["Close"].iloc[-1])
        sma_50 = float(hist["Close"].tail(C.SPY_SMA_SHORT).mean())
        sma_200 = float(hist["Close"].tail(C.SPY_SMA_LONG).mean())

        if last_close > sma_50 > sma_200:
            return C.REGIME_TRENDING_UP
        elif last_close < sma_50 < sma_200:
            return C.REGIME_TRENDING_DOWN
        else:
            return C.REGIME_RANGING

    def _get_vix_level(self) -> float:
        """Get the current VIX level."""
        try:
            vix = yf.Ticker("^VIX")
            hist = vix.history(period="1d")
            if hist.empty:
                return C.VIX_LOW_THRESHOLD  # Safe default
            return float(hist["Close"].iloc[-1])
        except Exception as e:
            logger.warning(f"Error getting VIX: {e}, using safe default")
            return C.VIX_LOW_THRESHOLD

    def scan_top_candidates(self) -> List[str]:
        """
        Scan the universe and return stocks with above-average volume.

        Returns:
            List of tickers with relative volume > 1.5x, max 10.
        """
        candidates: List[str] = []

        for ticker in self.base_universe:
            try:
                is_active = self._check_volume_activity(ticker)
                if is_active:
                    candidates.append(ticker)
            except Exception as e:
                logger.debug(f"Error screening {ticker}: {e}")
                continue

        logger.info(f"Screener found {len(candidates)} active candidates")
        return candidates[:10]

    def _check_volume_activity(self, ticker: str) -> bool:
        """Check if a ticker has above-average volume today."""
        t = yf.Ticker(ticker)
        data = t.history(period="2d")

        if len(data) < 2:
            return False

        current_vol = float(data["Volume"].iloc[-1])
        avg_vol = t.info.get("averageVolume", 1)

        return current_vol > avg_vol * C.RELATIVE_VOLUME_THRESHOLD
