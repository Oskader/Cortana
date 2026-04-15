"""
Trading Bot Autónomo v3
Groq + Alpaca + NewsAPI + Telegram

Mejoras v3:
- Nuevos indicadores: MACD, Bandas de Bollinger, ATR
- Sistema de confianza por puntos (cada indicador aporta/resta)
- Stop Loss dinámico basado en ATR (no porcentaje fijo)
- La IA recibe todos los indicadores calculados con sus puntuaciones
- Revisión cada 5 minutos en horario de mercado
- Ejecución totalmente automática
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

# ─── Watchlist ─────────────────────────────────────────────────────────────────
WATCHLIST = ["AAPL", "MSFT", "GOOGL", "NVDA", "META", "AMZN", "TSLA", "JPM", "V", "WMT"]

COMPANY_NAMES = {
    "AAPL": "Apple", "MSFT": "Microsoft", "GOOGL": "Google",
    "NVDA": "Nvidia", "META": "Meta Facebook", "AMZN": "Amazon",
    "TSLA": "Tesla", "JPM": "JPMorgan", "V": "Visa", "WMT": "Walmart"
}

# ─── Inversión según confianza ─────────────────────────────────────────────────
def get_investment_pct(confianza: int) -> float:
    if confianza <= 5:  return 0.00
    elif confianza <= 8: return 0.05
    elif confianza == 9: return 0.10
    else:               return 0.15

# ─── Prompt de la IA ───────────────────────────────────────────────────────────
TRADING_RULES = """
Eres un trader algorítmico experto. Recibirás datos técnicos ya analizados con una
puntuación pre-calculada por cada indicador, más noticias recientes.

Tu trabajo es revisar el análisis técnico, considerar las noticias, y dar una
decisión final con un nivel de confianza del 1 al 10.

PUNTUACIÓN DE INDICADORES (ya calculada, úsala como base):
Cada indicador tiene una puntuación parcial. La suma total te sugiere la confianza:
  - Suma 8-12 puntos  → confianza 9-10 (señal excepcional)
  - Suma 5-7 puntos   → confianza 7-8  (señal sólida)
  - Suma 2-4 puntos   → confianza 5-6  (señal débil)
  - Suma menor a 2    → confianza 1-4  (no operar)

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

recently_traded = {}

# ─── Calcular indicadores técnicos con puntuación ─────────────────────────────
def get_stock_data(symbol: str) -> Optional[dict]:
    try:
        request = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame.Day,
            start=datetime.now() - timedelta(days=90),
            end=datetime.now()
        )
        bars = data_client.get_stock_bars(request)
        df   = bars.df.reset_index()

        if df.empty or len(df) < 30:
            return None

        # ── Calcular todos los indicadores ──
        # RSI
        df["rsi"] = ta.momentum.RSIIndicator(df["close"], window=14).rsi()

        # SMA 50
        df["sma_50"] = ta.trend.SMAIndicator(df["close"], window=min(50, len(df))).sma_indicator()

        # MACD
        macd_ind       = ta.trend.MACD(df["close"], window_slow=26, window_fast=12, window_sign=9)
        df["macd"]     = macd_ind.macd()
        df["macd_sig"] = macd_ind.macd_signal()
        df["macd_diff"]= macd_ind.macd_diff()  # histograma

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

        precio    = float(latest["close"])
        rsi       = float(latest["rsi"])       if pd.notna(latest["rsi"])      else None
        sma_50    = float(latest["sma_50"])    if pd.notna(latest["sma_50"])   else None
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

        # ── Calcular puntuación por indicador ──
        puntos = {}
        total  = 0

        # RSI
        if rsi is not None:
            if rsi < 30:
                puntos["rsi"] = {"valor": round(rsi, 1), "pts": 3, "señal": "muy sobrevendida"}; total += 3
            elif rsi < 35:
                puntos["rsi"] = {"valor": round(rsi, 1), "pts": 2, "señal": "sobrevendida"}; total += 2
            elif rsi < 65:
                puntos["rsi"] = {"valor": round(rsi, 1), "pts": 0, "señal": "neutral"}
            elif rsi < 70:
                puntos["rsi"] = {"valor": round(rsi, 1), "pts": -1, "señal": "acercándose a sobrecompra"}; total -= 1
            else:
                puntos["rsi"] = {"valor": round(rsi, 1), "pts": -2, "señal": "sobrecomprada"}; total -= 2

        # SMA50
        if sma_50 is not None:
            diff_pct = (precio - sma_50) / sma_50 * 100
            if diff_pct > 2:
                puntos["sma50"] = {"valor": round(sma_50, 2), "diff_%": round(diff_pct, 1), "pts": 2, "señal": "tendencia alcista fuerte"}; total += 2
            elif diff_pct > 0:
                puntos["sma50"] = {"valor": round(sma_50, 2), "diff_%": round(diff_pct, 1), "pts": 1, "señal": "sobre la media"}; total += 1
            else:
                puntos["sma50"] = {"valor": round(sma_50, 2), "diff_%": round(diff_pct, 1), "pts": -1, "señal": "bajo la media"}; total -= 1

        # MACD
        if macd is not None and macd_sig is not None:
            cruce_alcista = macd_prev < macd_sig_p and macd > macd_sig  # cruzó hacia arriba
            cruce_bajista = macd_prev > macd_sig_p and macd < macd_sig  # cruzó hacia abajo
            if cruce_alcista:
                puntos["macd"] = {"valor": round(macd, 3), "señal_val": round(macd_sig, 3), "pts": 2, "señal": "cruce alcista reciente"}; total += 2
            elif macd > macd_sig and macd > 0:
                puntos["macd"] = {"valor": round(macd, 3), "señal_val": round(macd_sig, 3), "pts": 1, "señal": "positivo y subiendo"}; total += 1
            elif cruce_bajista:
                puntos["macd"] = {"valor": round(macd, 3), "señal_val": round(macd_sig, 3), "pts": -2, "señal": "cruce bajista reciente"}; total -= 2
            else:
                puntos["macd"] = {"valor": round(macd, 3), "señal_val": round(macd_sig, 3), "pts": -1, "señal": "negativo o bajando"}; total -= 1

        # Bandas de Bollinger
        if bb_upper is not None and bb_lower is not None and bb_mid is not None:
            rango = bb_upper - bb_lower
            pos   = (precio - bb_lower) / rango if rango > 0 else 0.5  # 0=banda inf, 1=banda sup
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

        # Volumen
        if vol_avg is not None and vol_avg > 0:
            ratio = volumen / vol_avg
            if ratio >= 1.5:
                puntos["volumen"] = {"hoy": volumen, "promedio": vol_avg, "ratio": round(ratio, 1), "pts": 1, "señal": "volumen alto confirma movimiento"}; total += 1
            elif ratio < 0.6:
                puntos["volumen"] = {"hoy": volumen, "promedio": vol_avg, "ratio": round(ratio, 1), "pts": -1, "señal": "volumen bajo, movimiento poco confiable"}; total -= 1
            else:
                puntos["volumen"] = {"hoy": volumen, "promedio": vol_avg, "ratio": round(ratio, 1), "pts": 0, "señal": "volumen normal"}

        # ATR para stop loss dinámico
        stop_loss_sugerido  = round(precio - (2 * atr), 2) if atr else None
        take_profit_sugerido= round(precio + (3 * atr), 2) if atr else None

        return {
            "simbolo":             symbol,
            "precio_actual":       round(precio, 2),
            "cambio_dia_%":        round((precio - float(prev["close"])) / float(prev["close"]) * 100, 2),
            "atr":                 round(atr, 2) if atr else None,
            "puntos_indicadores":  puntos,
            "puntos_total":        total,
            "stop_loss_sugerido":  stop_loss_sugerido,
            "take_profit_sugerido":take_profit_sugerido,
        }

    except Exception as e:
        log.error(f"Error obteniendo datos de {symbol}: {e}")
        return None

# ─── Noticias ──────────────────────────────────────────────────────────────────
def get_news(symbol: str) -> str:
    try:
        company = COMPANY_NAMES.get(symbol, symbol)
        url = (
            f"https://newsapi.org/v2/everything"
            f"?q={company}&language=en&sortBy=publishedAt"
            f"&from={(datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')}"
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
        "valor_total":        float(account.portfolio_value),
        "cash":               float(account.cash),
        "posiciones":         len(positions),
        "simbolos_abiertos":  [p.symbol for p in positions]
    }

# ─── Análisis con Groq ─────────────────────────────────────────────────────────
def analyze_with_groq(data: dict, portfolio: dict, noticias: str) -> Optional[dict]:
    prompt = f"""
Portafolio:
- Valor total: ${portfolio['valor_total']:,.2f}
- Cash disponible: ${portfolio['cash']:,.2f}
- Posiciones abiertas ({portfolio['posiciones']}): {portfolio['simbolos_abiertos']}

Análisis técnico de {data['simbolo']} (precio actual: ${data['precio_actual']}):
Cambio hoy: {data['cambio_dia_%']}%
ATR (volatilidad): {data['atr']}
Puntos técnicos totales: {data['puntos_total']} / 12 posibles

Detalle por indicador:
{json.dumps(data['puntos_indicadores'], indent=2, ensure_ascii=False)}

Stop loss sugerido por ATR: ${data['stop_loss_sugerido']}
Take profit sugerido por ATR: ${data['take_profit_sugerido']}

Noticias últimas 24h sobre {COMPANY_NAMES.get(data['simbolo'], data['simbolo'])}:
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

    try:
        if accion == "comprar":
            if symbol in portfolio["simbolos_abiertos"]:
                return None
            if symbol in recently_traded:
                if (datetime.now() - recently_traded[symbol]).seconds < 1800:
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

    # Detalle de cada indicador
    detalle = ""
    for ind, info in md.get("puntos_indicadores", {}).items():
        pts    = info.get("pts", 0)
        señal  = info.get("señal", "")
        signo  = "+" if pts > 0 else ""
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

# ─── Loop principal ────────────────────────────────────────────────────────────
async def analysis_loop():
    log.info("🚀 Bot v3 iniciado — MACD + Bollinger + ATR activos")

    ET = pytz.timezone("America/New_York")  # Zona horaria del NYSE/NASDAQ

    while True:
        now  = datetime.now(ET)   # Hora actual en Nueva York (correcta sin importar el servidor)
        hora = now.hour
        min_ = now.minute
        dia  = now.weekday()

        # Mercado abierto lunes-viernes 9:30am-4:00pm ET (hora de Nueva York)
        mercado_abierto = (
            dia < 5 and
            (hora > 9 or (hora == 9 and min_ >= 30)) and
            hora < 16
        )

        if mercado_abierto:
            log.info(f"🔍 Analizando mercado ({now.strftime('%H:%M')} ET)...")
            portfolio = get_portfolio_info()

            for symbol in WATCHLIST:
                try:
                    data = get_stock_data(symbol)
                    if data is None:
                        continue

                    pts = data["puntos_total"]
                    log.info(f"  {symbol}: {pts} pts técnicos")

                    # Si los puntos son muy bajos, ni consultamos a Groq
                    if pts < 2:
                        log.info(f"  ⏭️  {symbol}: puntos insuficientes, omitiendo")
                        continue

                    noticias = get_news(symbol)
                    decision = analyze_with_groq(data, portfolio, noticias)
                    if decision is None:
                        continue

                    confianza = decision["confianza"]
                    accion    = decision["accion"]
                    log.info(f"  {symbol}: {accion} — confianza {confianza}/10")

                    if accion in ("comprar", "vender") and confianza >= 6:
                        resultado = execute_order(decision, portfolio)
                        if resultado and not resultado.startswith("error"):
                            await notify_telegram(decision, resultado)
                            log.info(f"  ✅ Ejecutado y notificado: {symbol}")
                    else:
                        log.info(f"  ⏭️  {symbol}: confianza {confianza}/10, no opera")

                except Exception as e:
                    log.error(f"Error procesando {symbol}: {e}")

                await asyncio.sleep(3)

        else:
            log.info(f"  Mercado cerrado ({now.strftime('%H:%M')} ET). Revisando en 5 min...")

        await asyncio.sleep(5 * 60)


if __name__ == "__main__":
    asyncio.run(analysis_loop())