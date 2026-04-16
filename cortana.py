"""
Trading Bot Autónomo v4
Groq + Alpaca + NewsAPI + Telegram

Mejoras v4:
- Fix: Usa DataFeed.IEX en lugar de SIP (compatible con cuenta gratuita)
- Watchlist expandida: 75 acciones en 12 sectores
- RSI mejorado: distingue rebote vs caída libre
- Volumen direccional: volumen alto en día rojo = señal bajista
- Golden Cross / Death Cross con SMA20+SMA50
- Monitor automático de stop loss / take profit en posiciones abiertas
- Filtro de mercado general con SPY (no compra si mercado cae >2%)
- Cooldown ampliado a 4 horas por símbolo
- Sleep reducido a 1s entre acciones para caber en ~2 min por ciclo
"""

import os
import sys
import json
import asyncio
import logging
import requests
from datetime import datetime, timedelta
import pytz
from typing import Optional

from groq import Groq
import pandas as pd
import ta
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.data.enums import DataFeed          # ← NUEVO: necesario para IEX
from telegram import Bot

# Carga .env en local. En Railway las env vars ya están inyectadas por el servidor.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ─── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ─── Variables de entorno ──────────────────────────────────────────────────────
try:
    ALPACA_API_KEY    = os.environ["ALPACA_API_KEY"]
    ALPACA_SECRET_KEY = os.environ["ALPACA_SECRET_KEY"]
    GROQ_API_KEY      = os.environ["GROQ_API_KEY"]
    TELEGRAM_TOKEN    = os.environ["TELEGRAM_TOKEN"]
    TELEGRAM_CHAT_ID  = os.environ["TELEGRAM_CHAT_ID"]
    NEWS_API_KEY      = os.environ["NEWS_API_KEY"]
except KeyError as e:
    log.error(f"⚠️ ERROR FATAL: Falta configurar la variable de entorno {e} en el panel de Railway.")
    log.error("Por favor, entra a tu proyecto en Railway, ve a la pestaña 'Variables' y añádela.")
    sys.exit(1)

# ─── Watchlist 75 acciones (12 sectores) ──────────────────────────────────────
WATCHLIST = [
    # Tecnología (15)
    "AAPL", "MSFT", "GOOGL", "NVDA", "META", "AMZN", "AVGO", "CRM",
    "ORCL", "ADBE", "AMD", "INTC", "CSCO", "QCOM", "NOW",
    # Finanzas (10)
    "JPM", "V", "MA", "BAC", "GS", "BLK", "AXP", "C", "MS", "SCHW",
    # Salud (8)
    "UNH", "JNJ", "LLY", "PFE", "ABBV", "MRK", "TMO", "ABT",
    # Consumo (8)
    "WMT", "COST", "PG", "KO", "PEP", "MCD", "NKE", "SBUX",
    # Energía (5)
    "XOM", "CVX", "COP", "SLB", "EOG",
    # Industrial (7)
    "CAT", "HON", "UNP", "GE", "RTX", "LMT", "DE",
    # Comunicaciones (5)
    "NFLX", "DIS", "CMCSA", "TMUS", "VZ",
    # Real Estate (3)
    "AMT", "PLD", "CCI",
    # Materiales (3)
    "LIN", "APD", "SHW",
    # Utilities (3)
    "NEE", "DUK", "SO",
    # Automotriz/EV (3)
    "TSLA", "F", "GM",
    # Semiconductores (5)
    "TSM", "ASML", "MRVL", "MU", "LRCX",
]

COMPANY_NAMES = {
    "AAPL": "Apple", "MSFT": "Microsoft", "GOOGL": "Google", "NVDA": "Nvidia",
    "META": "Meta Facebook", "AMZN": "Amazon", "AVGO": "Broadcom", "CRM": "Salesforce",
    "ORCL": "Oracle", "ADBE": "Adobe", "AMD": "AMD", "INTC": "Intel",
    "CSCO": "Cisco", "QCOM": "Qualcomm", "NOW": "ServiceNow",
    "JPM": "JPMorgan", "V": "Visa", "MA": "Mastercard", "BAC": "Bank of America",
    "GS": "Goldman Sachs", "BLK": "BlackRock", "AXP": "American Express",
    "C": "Citigroup", "MS": "Morgan Stanley", "SCHW": "Charles Schwab",
    "UNH": "UnitedHealth", "JNJ": "Johnson Johnson", "LLY": "Eli Lilly",
    "PFE": "Pfizer", "ABBV": "AbbVie", "MRK": "Merck", "TMO": "Thermo Fisher",
    "ABT": "Abbott",
    "WMT": "Walmart", "COST": "Costco", "PG": "Procter Gamble",
    "KO": "Coca-Cola", "PEP": "PepsiCo", "MCD": "McDonald's", "NKE": "Nike",
    "SBUX": "Starbucks",
    "XOM": "ExxonMobil", "CVX": "Chevron", "COP": "ConocoPhillips",
    "SLB": "Schlumberger", "EOG": "EOG Resources",
    "CAT": "Caterpillar", "HON": "Honeywell", "UNP": "Union Pacific",
    "GE": "General Electric", "RTX": "Raytheon", "LMT": "Lockheed Martin",
    "DE": "Deere",
    "NFLX": "Netflix", "DIS": "Disney", "CMCSA": "Comcast", "TMUS": "T-Mobile",
    "VZ": "Verizon",
    "AMT": "American Tower", "PLD": "Prologis", "CCI": "Crown Castle",
    "LIN": "Linde", "APD": "Air Products", "SHW": "Sherwin-Williams",
    "NEE": "NextEra Energy", "DUK": "Duke Energy", "SO": "Southern Company",
    "TSLA": "Tesla", "F": "Ford", "GM": "General Motors",
    "TSM": "Taiwan Semiconductor", "ASML": "ASML Holding", "MRVL": "Marvell Technology",
    "MU": "Micron Technology", "LRCX": "Lam Research",
    "SPY": "S&P 500 ETF",     # para el filtro de mercado
}

# ─── Inversión según confianza ─────────────────────────────────────────────────
def get_investment_pct(confianza: int) -> float:
    if confianza <= 5:  return 0.00
    elif confianza <= 8: return 0.05
    elif confianza == 9: return 0.10
    else:               return 0.15

# ─── Estado global ─────────────────────────────────────────────────────────────
recently_traded   = {}                   # symbol → datetime de la última operación
position_targets  = {}                   # symbol → {"stop_loss": x, "take_profit": y}

# ─── Prompt de la IA ───────────────────────────────────────────────────────────
TRADING_RULES = """
Eres un trader algorítmico experto. Recibirás datos técnicos ya analizados con una
puntuación pre-calculada por cada indicador, más noticias recientes.

Tu trabajo es revisar el análisis técnico, considerar las noticias, y dar una
decisión final con un nivel de confianza del 1 al 10.

PUNTUACIÓN DE INDICADORES (ya calculada, úsala como base):
Cada indicador tiene una puntuación parcial. La suma total te sugiere la confianza:
  - Suma 10-15 puntos → confianza 9-10 (señal excepcional)
  - Suma 6-9 puntos   → confianza 7-8  (señal sólida)
  - Suma 3-5 puntos   → confianza 5-6  (señal débil)
  - Suma menor a 3    → confianza 1-4  (no operar)

AJUSTE POR NOTICIAS:
  - Noticias muy positivas (contrato enorme, ganancias récord): +1 o +2 a la confianza
  - Noticias neutras o sin noticias: sin cambio
  - Noticias negativas moderadas: -1 o -2
  - Noticias graves (bancarrota, fraude, escándalo): confianza final máxima = 3, acción = "nada"

STOP LOSS DINÁMICO (basado en ATR):
  - Usa el ATR recibido para calcular stop_loss = precio_actual - (2 × ATR)
  - Usa take_profit = precio_actual + (3 × ATR)
  - Esto hace que el stop loss se adapte a la volatilidad real de la acción

ESCALA DE INVERSIÓN (para incluir en tu razonamiento):
  - Confianza 1-5:  no operar
  - Confianza 6-8:  5% del portafolio
  - Confianza 9:    10% del portafolio
  - Confianza 10:   15% del portafolio

Responde ÚNICAMENTE con este JSON, sin texto adicional:
{
  "accion": "comprar" o "vender" o "nada",
  "simbolo": "TICKER",
  "confianza": numero del 1 al 10,
  "puntos_tecnicos": numero (suma de puntos de indicadores),
  "razon_tecnica": "explicación clara en español de los indicadores",
  "razon_noticias": "impacto de las noticias en la decisión",
  "stop_loss": numero,
  "take_profit": numero
}
"""

# ─── Clientes ──────────────────────────────────────────────────────────────────
trading_client = TradingClient(ALPACA_API_KEY, ALPACA_SECRET_KEY, paper=True)
data_client    = StockHistoricalDataClient(ALPACA_API_KEY, ALPACA_SECRET_KEY)
groq_client    = Groq(api_key=GROQ_API_KEY)
telegram_bot   = Bot(token=TELEGRAM_TOKEN)


# ─── Obtener datos de mercado (usa IEX — feed gratuito) ───────────────────────
def get_stock_data(symbol: str) -> Optional[dict]:
    try:
        # FIX: feed=DataFeed.IEX para evitar el error "subscription does not permit querying recent SIP data"
        # FIX: end 16 min atrás para datos consolidados sin restricción de tiempo real
        request = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame.Day,
            start=datetime.now() - timedelta(days=120),
            end=datetime.now() - timedelta(minutes=16),
            feed=DataFeed.IEX
        )
        bars = data_client.get_stock_bars(request)
        df   = bars.df.reset_index()

        if df.empty or len(df) < 35:
            return None

        # ── Calcular todos los indicadores ──

        # RSI
        df["rsi"] = ta.momentum.RSIIndicator(df["close"], window=14).rsi()

        # SMA 20 y SMA 50 (para detectar Golden/Death Cross)
        df["sma_20"] = ta.trend.SMAIndicator(df["close"], window=min(20, len(df))).sma_indicator()
        df["sma_50"] = ta.trend.SMAIndicator(df["close"], window=min(50, len(df))).sma_indicator()

        # MACD
        macd_ind       = ta.trend.MACD(df["close"], window_slow=26, window_fast=12, window_sign=9)
        df["macd"]     = macd_ind.macd()
        df["macd_sig"] = macd_ind.macd_signal()
        df["macd_diff"]= macd_ind.macd_diff()

        # Bandas de Bollinger
        bb             = ta.volatility.BollingerBands(df["close"], window=20, window_dev=2)
        df["bb_upper"] = bb.bollinger_hband()
        df["bb_lower"] = bb.bollinger_lband()
        df["bb_mid"]   = bb.bollinger_mavg()

        # ATR (volatilidad real)
        df["atr"] = ta.volatility.AverageTrueRange(df["high"], df["low"], df["close"], window=14).average_true_range()

        # Volumen promedio
        df["vol_avg"] = df["volume"].rolling(window=20).mean()

        latest = df.iloc[-1]
        prev   = df.iloc[-2]
        prev2  = df.iloc[-3]     # para confirmar dirección del RSI

        precio     = float(latest["close"])
        precio_ant = float(prev["close"])
        dia_verde  = precio > precio_ant     # True = día alcista

        rsi       = float(latest["rsi"])       if pd.notna(latest["rsi"])      else None
        rsi_prev  = float(prev["rsi"])         if pd.notna(prev["rsi"])        else None
        sma_20    = float(latest["sma_20"])    if pd.notna(latest["sma_20"])   else None
        sma_50    = float(latest["sma_50"])    if pd.notna(latest["sma_50"])   else None
        sma_20_p  = float(prev["sma_20"])      if pd.notna(prev["sma_20"])     else None
        sma_50_p  = float(prev["sma_50"])      if pd.notna(prev["sma_50"])     else None
        macd      = float(latest["macd"])      if pd.notna(latest["macd"])     else None
        macd_sig  = float(latest["macd_sig"])  if pd.notna(latest["macd_sig"]) else None
        macd_prev = float(prev["macd"])        if pd.notna(prev["macd"])       else None
        macd_sig_p= float(prev["macd_sig"])    if pd.notna(prev["macd_sig"])   else None
        bb_upper  = float(latest["bb_upper"])  if pd.notna(latest["bb_upper"]) else None
        bb_lower  = float(latest["bb_lower"])  if pd.notna(latest["bb_lower"]) else None
        bb_mid    = float(latest["bb_mid"])    if pd.notna(latest["bb_mid"])   else None
        atr       = float(latest["atr"])       if pd.notna(latest["atr"])      else None
        volumen   = int(latest["volume"])
        vol_avg   = int(latest["vol_avg"])     if pd.notna(latest["vol_avg"])  else None

        # ── Calcular puntuación mejorada por indicador ──
        puntos = {}
        total  = 0

        # ── RSI MEJORADO: considera si está subiendo (rebote) o bajando (caída libre) ──
        if rsi is not None and rsi_prev is not None:
            rsi_subiendo = rsi > rsi_prev
            if rsi < 30 and rsi_subiendo:
                puntos["rsi"] = {"valor": round(rsi, 1), "pts": 3, "señal": "sobrevendida + rebotando ↑"}; total += 3
            elif rsi < 30 and not rsi_subiendo:
                puntos["rsi"] = {"valor": round(rsi, 1), "pts": 0, "señal": "sobrevendida pero aún cayendo (caída libre, esperar)"}
            elif rsi < 35 and rsi_subiendo:
                puntos["rsi"] = {"valor": round(rsi, 1), "pts": 2, "señal": "zona sobrevendida + subiendo"}; total += 2
            elif rsi < 65:
                puntos["rsi"] = {"valor": round(rsi, 1), "pts": 0, "señal": "neutral"}
            elif rsi < 70:
                puntos["rsi"] = {"valor": round(rsi, 1), "pts": -1, "señal": "acercándose a sobrecompra"}; total -= 1
            else:
                puntos["rsi"] = {"valor": round(rsi, 1), "pts": -2, "señal": "sobrecomprada"}; total -= 2

        # ── GOLDEN CROSS / DEATH CROSS (SMA20 vs SMA50) ──
        if sma_20 is not None and sma_50 is not None and sma_20_p is not None and sma_50_p is not None:
            golden_cross = sma_20_p < sma_50_p and sma_20 >= sma_50   # SMA20 cruzó SMA50 hacia arriba
            death_cross  = sma_20_p > sma_50_p and sma_20 <= sma_50   # SMA20 cruzó SMA50 hacia abajo
            diff_pct     = (precio - sma_50) / sma_50 * 100

            if golden_cross:
                puntos["sma_cross"] = {"sma20": round(sma_20, 2), "sma50": round(sma_50, 2), "pts": 3, "señal": "Golden Cross: SMA20 cruzó SMA50 ↑"}; total += 3
            elif death_cross:
                puntos["sma_cross"] = {"sma20": round(sma_20, 2), "sma50": round(sma_50, 2), "pts": -3, "señal": "Death Cross: SMA20 cruzó SMA50 ↓"}; total -= 3
            elif sma_20 > sma_50 and diff_pct > 2:
                puntos["sma_cross"] = {"sma20": round(sma_20, 2), "sma50": round(sma_50, 2), "diff_%": round(diff_pct, 1), "pts": 2, "señal": "SMA20 > SMA50, tendencia alcista"}; total += 2
            elif sma_20 > sma_50:
                puntos["sma_cross"] = {"sma20": round(sma_20, 2), "sma50": round(sma_50, 2), "diff_%": round(diff_pct, 1), "pts": 1, "señal": "sobre medias móviles"}; total += 1
            else:
                puntos["sma_cross"] = {"sma20": round(sma_20, 2), "sma50": round(sma_50, 2), "diff_%": round(diff_pct, 1), "pts": -1, "señal": "SMA20 < SMA50, tendencia bajista"}; total -= 1

        # ── MACD ──
        if macd is not None and macd_sig is not None:
            cruce_alcista = macd_prev < macd_sig_p and macd > macd_sig
            cruce_bajista = macd_prev > macd_sig_p and macd < macd_sig
            if cruce_alcista:
                puntos["macd"] = {"valor": round(macd, 3), "señal_val": round(macd_sig, 3), "pts": 2, "señal": "cruce alcista reciente ↑"}; total += 2
            elif macd > macd_sig and macd > 0:
                puntos["macd"] = {"valor": round(macd, 3), "señal_val": round(macd_sig, 3), "pts": 1, "señal": "positivo y subiendo"}; total += 1
            elif cruce_bajista:
                puntos["macd"] = {"valor": round(macd, 3), "señal_val": round(macd_sig, 3), "pts": -2, "señal": "cruce bajista reciente ↓"}; total -= 2
            else:
                puntos["macd"] = {"valor": round(macd, 3), "señal_val": round(macd_sig, 3), "pts": -1, "señal": "negativo o bajando"}; total -= 1

        # ── Bandas de Bollinger ──
        if bb_upper is not None and bb_lower is not None and bb_mid is not None:
            rango = bb_upper - bb_lower
            pos   = (precio - bb_lower) / rango if rango > 0 else 0.5
            if pos <= 0.1:
                puntos["bollinger"] = {"precio_vs_banda": round(pos*100, 1), "bb_lower": round(bb_lower, 2), "bb_upper": round(bb_upper, 2), "pts": 2, "señal": "tocando banda inferior (muy barato)"}; total += 2
            elif pos <= 0.35:
                puntos["bollinger"] = {"precio_vs_banda": round(pos*100, 1), "bb_lower": round(bb_lower, 2), "bb_upper": round(bb_upper, 2), "pts": 1, "señal": "tercio inferior de las bandas"}; total += 1
            elif pos <= 0.65:
                puntos["bollinger"] = {"precio_vs_banda": round(pos*100, 1), "bb_lower": round(bb_lower, 2), "bb_upper": round(bb_upper, 2), "pts": 0, "señal": "zona media"}
            elif pos <= 0.9:
                puntos["bollinger"] = {"precio_vs_banda": round(pos*100, 1), "bb_lower": round(bb_lower, 2), "bb_upper": round(bb_upper, 2), "pts": -1, "señal": "tercio superior"}; total -= 1
            else:
                puntos["bollinger"] = {"precio_vs_banda": round(pos*100, 1), "bb_lower": round(bb_lower, 2), "bb_upper": round(bb_upper, 2), "pts": -2, "señal": "tocando banda superior (muy caro)"}; total -= 2

        # ── VOLUMEN DIRECCIONAL: considera si el día es verde o rojo ──
        if vol_avg is not None and vol_avg > 0:
            ratio = volumen / vol_avg
            if ratio >= 1.5 and dia_verde:
                puntos["volumen"] = {"hoy": volumen, "promedio": vol_avg, "ratio": round(ratio, 1), "pts": 2, "señal": "volumen alto en día VERDE — confirmación alcista fuerte"}; total += 2
            elif ratio >= 1.5 and not dia_verde:
                puntos["volumen"] = {"hoy": volumen, "promedio": vol_avg, "ratio": round(ratio, 1), "pts": -2, "señal": "volumen alto en día ROJO — venta masiva (señal bajista)"}; total -= 2
            elif ratio >= 1.2 and dia_verde:
                puntos["volumen"] = {"hoy": volumen, "promedio": vol_avg, "ratio": round(ratio, 1), "pts": 1, "señal": "volumen elevado confirma subida"}; total += 1
            elif ratio < 0.6:
                puntos["volumen"] = {"hoy": volumen, "promedio": vol_avg, "ratio": round(ratio, 1), "pts": -1, "señal": "volumen bajo, movimiento poco confiable"}; total -= 1
            else:
                puntos["volumen"] = {"hoy": volumen, "promedio": vol_avg, "ratio": round(ratio, 1), "pts": 0, "señal": "volumen normal"}

        # ATR para stop loss dinámico
        stop_loss_sugerido   = round(precio - (2 * atr), 2) if atr else None
        take_profit_sugerido = round(precio + (3 * atr), 2) if atr else None

        return {
            "simbolo":              symbol,
            "precio_actual":        round(precio, 2),
            "cambio_dia_%":         round((precio - precio_ant) / precio_ant * 100, 2),
            "dia_verde":            dia_verde,
            "atr":                  round(atr, 2) if atr else None,
            "puntos_indicadores":   puntos,
            "puntos_total":         total,
            "stop_loss_sugerido":   stop_loss_sugerido,
            "take_profit_sugerido": take_profit_sugerido,
        }

    except Exception as e:
        log.error(f"Error obteniendo datos de {symbol}: {e}")
        return None


# ─── Filtro de mercado general (SPY) ──────────────────────────────────────────
def get_spy_market_condition() -> dict:
    """
    Devuelve el estado general del mercado basado en SPY.
    Returns: {"cambio_%": float, "condicion": "bull"/"bear"/"crash"}
    """
    try:
        data = get_stock_data("SPY")
        if data is None:
            return {"cambio_%": 0, "condicion": "unknown"}
        cambio = data["cambio_dia_%"]
        if cambio <= -2.0:
            condicion = "crash"      # mercado en caída libre → no comprar
        elif cambio <= -1.0:
            condicion = "bear"       # mercado bajista → limitar compras
        elif cambio >= 1.0:
            condicion = "bull"       # mercado alcista → operar normal
        else:
            condicion = "neutral"
        return {"cambio_%": cambio, "condicion": condicion}
    except Exception as e:
        log.warning(f"No se pudo obtener condición SPY: {e}")
        return {"cambio_%": 0, "condicion": "unknown"}


# ─── Monitor de posiciones abiertas (stop loss / take profit automático) ──────
def check_open_positions(portfolio: dict) -> list:
    """
    Revisa todas las posiciones abiertas. Si alguna alcanzó su stop loss
    o take profit guardados, la cierra automáticamente.
    Retorna lista de símbolos cerrados.
    """
    cerrados = []
    try:
        positions = trading_client.get_all_positions()
        for pos in positions:
            symbol  = pos.symbol
            current = float(pos.current_price)
            targets = position_targets.get(symbol)
            if not targets:
                continue

            sl = targets.get("stop_loss")
            tp = targets.get("take_profit")
            razon = None

            if sl and current <= sl:
                razon = f"STOP LOSS alcanzado: ${current:.2f} ≤ ${sl:.2f}"
            elif tp and current >= tp:
                razon = f"TAKE PROFIT alcanzado: ${current:.2f} ≥ ${tp:.2f}"

            if razon:
                qty = float(pos.qty)
                try:
                    trading_client.submit_order(MarketOrderRequest(
                        symbol=symbol, qty=qty,
                        side=OrderSide.SELL, time_in_force=TimeInForce.DAY
                    ))
                    log.info(f"  🔒 Cerrada posición {symbol} — {razon}")
                    cerrados.append({"symbol": symbol, "razon": razon, "precio": current, "qty": qty})
                    position_targets.pop(symbol, None)
                    recently_traded[symbol] = datetime.now()
                except Exception as e:
                    log.error(f"  Error cerrando {symbol}: {e}")
    except Exception as e:
        log.error(f"Error monitoreando posiciones: {e}")
    return cerrados


# ─── Noticias ──────────────────────────────────────────────────────────────────
def get_news(symbol: str) -> str:
    try:
        company = COMPANY_NAMES.get(symbol, symbol)
        url = (
            f"https://newsapi.org/v2/everything"
            f"?q={company}&language=en&sortBy=publishedAt"
            f"&from={(datetime.now() - timedelta(days=2)).strftime('%Y-%m-%d')}"
            f"&pageSize=5&apiKey={NEWS_API_KEY}"
        )
        resp = requests.get(url, timeout=10)
        data = resp.json()
        if data.get("status") != "ok" or not data.get("articles"):
            return "Sin noticias recientes."
        return "\n".join([f"- {a['title']}" for a in data["articles"][:5]])
    except Exception as e:
        log.error(f"Error noticias {symbol}: {e}")
        return "No se pudieron obtener noticias."


# ─── Info portafolio ───────────────────────────────────────────────────────────
def get_portfolio_info() -> dict:
    account   = trading_client.get_account()
    positions = trading_client.get_all_positions()
    return {
        "valor_total":       float(account.portfolio_value),
        "cash":              float(account.cash),
        "posiciones":        len(positions),
        "simbolos_abiertos": [p.symbol for p in positions]
    }


# ─── Análisis con Groq ─────────────────────────────────────────────────────────
def analyze_with_groq(data: dict, portfolio: dict, noticias: str, spy_condicion: str) -> Optional[dict]:
    aviso_mercado = ""
    if spy_condicion == "crash":
        aviso_mercado = "\n⚠️ ALERTA: El mercado general (SPY) está en caída >2% hoy. Sé muy conservador, preferiblemente no compres."
    elif spy_condicion == "bear":
        aviso_mercado = "\n⚠️ AVISO: El mercado general (SPY) está bajando hoy (-1% a -2%). Limita la confianza máxima a 7."

    prompt = f"""
Portafolio:
- Valor total: ${portfolio['valor_total']:,.2f}
- Cash disponible: ${portfolio['cash']:,.2f}
- Posiciones abiertas ({portfolio['posiciones']}): {portfolio['simbolos_abiertos']}
{aviso_mercado}

Análisis técnico de {data['simbolo']} (precio actual: ${data['precio_actual']}):
Cambio hoy: {data['cambio_dia_%']}% {'🟢' if data['dia_verde'] else '🔴'}
ATR (volatilidad): {data['atr']}
Puntos técnicos totales: {data['puntos_total']} / 15 posibles

Detalle por indicador:
{json.dumps(data['puntos_indicadores'], indent=2, ensure_ascii=False)}

Stop loss sugerido por ATR: ${data['stop_loss_sugerido']}
Take profit sugerido por ATR: ${data['take_profit_sugerido']}

Noticias últimas 48h sobre {COMPANY_NAMES.get(data['simbolo'], data['simbolo'])}:
{noticias}

Basándote en el puntaje técnico y las noticias, dame tu decisión en JSON.
"""

    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": TRADING_RULES},
                {"role": "user",   "content": prompt}
            ],
            max_tokens=500
        )
        raw    = response.choices[0].message.content.strip()
        raw    = raw.replace("```json", "").replace("```", "").strip()
        result = json.loads(raw)
        result["market_data"] = data
        return result
    except Exception as e:
        log.error(f"Error Groq {data['simbolo']}: {e}")
        return None


# ─── Ejecutar orden ────────────────────────────────────────────────────────────
def execute_order(decision: dict, portfolio: dict) -> Optional[str]:
    symbol    = decision["simbolo"]
    accion    = decision["accion"]
    confianza = decision["confianza"]
    precio    = decision["market_data"]["precio_actual"]
    pct       = get_investment_pct(confianza)

    if pct == 0:
        return None

    # Cooldown ampliado a 4 horas (era 30 min)
    COOLDOWN_SECONDS = 4 * 60 * 60

    try:
        if accion == "comprar":
            if symbol in portfolio["simbolos_abiertos"]:
                return None
            if symbol in recently_traded:
                if (datetime.now() - recently_traded[symbol]).seconds < COOLDOWN_SECONDS:
                    return None

            monto    = portfolio["valor_total"] * pct
            cantidad = int(min(monto, portfolio["cash"]) / precio)
            if cantidad < 1:
                return None

            order = trading_client.submit_order(MarketOrderRequest(
                symbol=symbol, qty=cantidad,
                side=OrderSide.BUY, time_in_force=TimeInForce.DAY
            ))
            recently_traded[symbol] = datetime.now()

            # Guardar targets para el monitor de posiciones
            position_targets[symbol] = {
                "stop_loss":   decision.get("stop_loss"),
                "take_profit": decision.get("take_profit"),
            }

            return f"compra|{cantidad}|{precio}|{pct*100:.0f}|{order.id}"

        elif accion == "vender":
            positions = {p.symbol: p for p in trading_client.get_all_positions()}
            if symbol not in positions:
                return None
            qty   = float(positions[symbol].qty)
            order = trading_client.submit_order(MarketOrderRequest(
                symbol=symbol, qty=qty,
                side=OrderSide.SELL, time_in_force=TimeInForce.DAY
            ))
            recently_traded[symbol] = datetime.now()
            position_targets.pop(symbol, None)
            return f"venta|{qty}|{precio}|{pct*100:.0f}|{order.id}"

    except Exception as e:
        log.error(f"Error orden {symbol}: {e}")
        return f"error|{e}"

    return None


# ─── Notificación Telegram ─────────────────────────────────────────────────────
async def notify_telegram(decision: dict, resultado: str):
    md     = decision["market_data"]
    partes = resultado.split("|")

    if partes[0] == "error":
        await telegram_bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=f"❌ Error ejecutando {decision['simbolo']}: {partes[1]}"
        )
        return

    tipo, cantidad, precio, pct, orden_id = partes
    emoji  = "🟢" if tipo == "compra" else "🔴"
    stars  = "⭐" * decision["confianza"]
    puntos = md.get("puntos_total", "?")

    detalle = ""
    for ind, info in md.get("puntos_indicadores", {}).items():
        pts   = info.get("pts", 0)
        señal = info.get("señal", "")
        signo = "+" if pts > 0 else ""
        detalle += f"  • {ind.upper()}: `{signo}{pts}` — _{señal}_\n"

    texto = (
        f"{emoji} *{tipo.upper()} ejecutada automáticamente*\n\n"
        f"*{decision['simbolo']}* — `${precio}`\n\n"
        f"📊 *Indicadores ({puntos} pts totales):*\n"
        f"{detalle}\n"
        f"📰 *Noticias:* _{decision.get('razon_noticias', 'Sin noticias relevantes')}_\n\n"
        f"💼 *Operación:*\n"
        f"  • Cantidad: `{cantidad} acciones`\n"
        f"  • Monto: `{pct}% del portafolio`\n"
        f"  • Stop Loss: `${decision.get('stop_loss', 'N/A')}`\n"
        f"  • Take Profit: `${decision.get('take_profit', 'N/A')}`\n\n"
        f"🧠 _{decision.get('razon_tecnica', '')}_\n\n"
        f"💪 Confianza: {stars} `{decision['confianza']}/10`"
    )

    await telegram_bot.send_message(
        chat_id=TELEGRAM_CHAT_ID,
        text=texto,
        parse_mode="Markdown"
    )


async def notify_position_closed(info: dict):
    texto = (
        f"🔒 *Posición cerrada automáticamente*\n\n"
        f"*{info['symbol']}* — `${info['precio']:.2f}`\n"
        f"📋 Razón: _{info['razon']}_\n"
        f"📦 Cantidad: `{info['qty']} acciones`"
    )
    try:
        await telegram_bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=texto,
            parse_mode="Markdown"
        )
    except Exception as e:
        log.error(f"Error notificando cierre de posición: {e}")


# ─── Loop principal ────────────────────────────────────────────────────────────
async def analysis_loop():
    log.info("🚀 Bot v4 iniciado — IEX feed + 75 acciones + algoritmo mejorado")

    ET = pytz.timezone("America/New_York")

    while True:
        now  = datetime.now(ET)
        hora = now.hour
        min_ = now.minute
        dia  = now.weekday()

        mercado_abierto = (
            dia < 5 and
            (hora > 9 or (hora == 9 and min_ >= 30)) and
            hora < 16
        )

        if mercado_abierto:
            log.info(f"🔍 Analizando mercado ({now.strftime('%H:%M')} ET) — {len(WATCHLIST)} acciones...")

            # ── 1. Monitor de posiciones abiertas (stop loss / take profit) ──
            portfolio = get_portfolio_info()
            cerrados  = check_open_positions(portfolio)
            for info in cerrados:
                await notify_position_closed(info)

            # ── 2. Condición general del mercado (SPY) ──
            spy = get_spy_market_condition()
            log.info(f"  📈 SPY: {spy['cambio_%']:+.2f}% — Mercado: {spy['condicion'].upper()}")

            if spy["condicion"] == "crash":
                log.warning("  ⚠️ Mercado en CRASH (-2%). Solo se monitorean posiciones, no se compra.")

            # ── 3. Refrescar portafolio ──
            portfolio = get_portfolio_info()

            # ── 4. Analizar cada símbolo ──
            for symbol in WATCHLIST:
                try:
                    data = get_stock_data(symbol)
                    if data is None:
                        continue

                    pts = data["puntos_total"]
                    log.info(f"  {symbol}: {pts:+d} pts técnicos ({data['cambio_dia_%']:+.1f}%)")

                    # Filtro mínimo de puntos (más alto con 75 acciones para no saturar Groq)
                    umbral = 3
                    if pts < umbral:
                        log.info(f"  ⏭️  {symbol}: puntos insuficientes ({pts}<{umbral}), omitiendo")
                        continue

                    # Si el mercado está en crash, solo analizar posiciones ya abiertas
                    if spy["condicion"] == "crash" and symbol not in portfolio["simbolos_abiertos"]:
                        continue

                    noticias = get_news(symbol)
                    decision = analyze_with_groq(data, portfolio, noticias, spy["condicion"])
                    if decision is None:
                        continue

                    confianza = decision["confianza"]
                    accion    = decision["accion"]

                    # En mercado bear, limitar confianza máxima a 6
                    if spy["condicion"] == "bear" and confianza > 6:
                        confianza = 6
                        decision["confianza"] = 6
                        log.info(f"  ⚠️  {symbol}: confianza limitada a 6 por mercado bajista")

                    log.info(f"  {symbol}: {accion} — confianza {confianza}/10")

                    if accion in ("comprar", "vender") and confianza >= 6:
                        resultado = execute_order(decision, portfolio)
                        if resultado and not resultado.startswith("error"):
                            await notify_telegram(decision, resultado)
                            log.info(f"  ✅ Ejecutado y notificado: {symbol}")
                        elif resultado and resultado.startswith("error"):
                            log.error(f"  ❌ Error en orden {symbol}: {resultado}")
                    else:
                        log.info(f"  ⏭️  {symbol}: confianza {confianza}/10, no opera")

                except Exception as e:
                    log.error(f"Error procesando {symbol}: {e}")

                # Reducido a 1s (era 3s) para procesar 75 acciones en ~2 min
                await asyncio.sleep(1)

        else:
            log.info(f"  Mercado cerrado ({now.strftime('%H:%M')} ET). Revisando en 5 min...")

        await asyncio.sleep(5 * 60)


if __name__ == "__main__":
    asyncio.run(analysis_loop())