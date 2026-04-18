import yfinance as yf
import pandas as pd
from loguru import logger
from ..config.settings import settings
from typing import List

class Screener:
    def __init__(self):
        # Lista de candidatos (puedes ampliarla)
        self.base_universe = [
            "AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "NVDA", "BRK-B", "JPM", "V",
            "UNH", "MA", "PG", "HD", "DIS", "PYPL", "BAC", "VZ", "ADBE", "CMCSA",
            "NFLX", "KO", "PEP", "INTC", "CSCO", "AVGO", "COST", "TMO", "PFE", "ABT"
        ]

    def get_market_regime(self) -> str:
        """Determina si el mercado es alcista, bajista o rango usando SPY"""
        try:
            spy = yf.Ticker("SPY")
            hist = spy.history(period="200d")
            
            last_close = hist['Close'].iloc[-1]
            sma_50 = hist['Close'].tail(50).mean()
            sma_200 = hist['Close'].tail(200).mean()
            
            vix = yf.Ticker("^VIX").history(period="1d")['Close'].iloc[-1]
            
            if vix > 25:
                return "HIGH_VOLATILITY"
            elif last_close > sma_50 > sma_200:
                return "TRENDING_UP"
            elif last_close < sma_50 < sma_200:
                return "TRENDING_DOWN"
            else:
                return "RANGING"
        except Exception as e:
            logger.error(f"Error detectando régimen de mercado: {e}")
            return "NEUTRAL"

    def scan_top_candidates(self) -> List[str]:
        """Escanea el universo y devuelve los top 10 con mayor volumen relativo"""
        candidates = []
        for ticker in self.base_universe:
            try:
                t = yf.Ticker(ticker)
                data = t.history(period="2d")
                if len(data) < 2: continue
                
                vol = data['Volume'].iloc[-1]
                avg_vol = t.info.get('averageVolume', 1)
                
                if vol > avg_vol * 1.5:
                    candidates.append(ticker)
            except:
                continue
        
        return candidates[:10]
