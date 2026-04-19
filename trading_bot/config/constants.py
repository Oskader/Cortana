"""
Constantes globales del bot de trading Cortana.
Centraliza todos los magic numbers para mantener configuración declarativa.
"""

# ═══════════════════════════════════════════
# INDICADORES TÉCNICOS — Períodos
# ═══════════════════════════════════════════
EMA_FAST_PERIOD: int = 9
EMA_MID_PERIOD: int = 21
EMA_SLOW_PERIOD: int = 50
EMA_TREND_PERIOD: int = 200

RSI_PERIOD: int = 14
RSI_OVERSOLD: float = 30.0
RSI_OVERBOUGHT: float = 70.0
RSI_BULLISH_MIN: float = 40.0
RSI_BULLISH_MAX: float = 65.0

MACD_FAST: int = 12
MACD_SLOW: int = 26
MACD_SIGNAL: int = 9

BBANDS_PERIOD: int = 20
BBANDS_STD: float = 2.0

ATR_PERIOD: int = 14
SUPERTREND_PERIOD: int = 10
SUPERTREND_MULTIPLIER: float = 3.0

VOLUME_SMA_PERIOD: int = 20
RELATIVE_VOLUME_THRESHOLD: float = 1.5

# ═══════════════════════════════════════════
# SIGNAL SCORING — Pesos (máximo 100)
# ═══════════════════════════════════════════
SCORE_EMA_STACK: int = 20
SCORE_RSI_CONTEXT: int = 15
SCORE_MACD_CROSS: int = 20
SCORE_ABOVE_VWAP: int = 15
SCORE_RELATIVE_VOLUME: int = 10
SCORE_SUPERTREND: int = 20

SCORE_STRONG_SIGNAL: int = 70
SCORE_MODERATE_SIGNAL: int = 50

# ═══════════════════════════════════════════
# RISK MANAGEMENT
# ═══════════════════════════════════════════
ATR_MULTIPLIER_LOW_VOL: float = 1.5
ATR_MULTIPLIER_HIGH_VOL: float = 2.5
VIX_HIGH_THRESHOLD: float = 25.0
VIX_LOW_THRESHOLD: float = 20.0

DRAWDOWN_HARD_LIMIT: float = 0.05  # 5%
BUYING_POWER_BUFFER: float = 1.10  # 10% buffer
MIN_RISK_REWARD_RATIO: float = 1.5

KELLY_MIN_FRACTION: float = 0.01
KELLY_FALLBACK_EQUITY: float = 1000.0
KELLY_MIN_SAMPLE_SIZE: int = 20

HIGH_VOL_SIZE_REDUCTION: float = 0.50  # 50% del tamaño en alta volatilidad

# ═══════════════════════════════════════════
# GROQ AI
# ═══════════════════════════════════════════
GROQ_TIMEOUT_SECONDS: int = 15
GROQ_MAX_RETRIES: int = 3
GROQ_TEMPERATURE: float = 0.1

# ═══════════════════════════════════════════
# INFRASTRUCTURE — Intervalos
# ═══════════════════════════════════════════
STATE_UPDATE_INTERVAL_SECONDS: int = 60
SCAN_INTERVAL_SECONDS: int = 300
SCAN_TICKER_DELAY_SECONDS: int = 2
WEBSOCKET_RECONNECT_DELAY_SECONDS: int = 5
WEBSOCKET_QUEUE_MAX_SIZE: int = 100

MIN_BARS_FOR_INDICATORS: int = 50
DEFAULT_BAR_LIMIT: int = 200

# ═══════════════════════════════════════════
# MARKET REGIME — Labels
# ═══════════════════════════════════════════
REGIME_TRENDING_UP: str = "TRENDING_UP"
REGIME_TRENDING_DOWN: str = "TRENDING_DOWN"
REGIME_RANGING: str = "RANGING"
REGIME_HIGH_VOLATILITY: str = "HIGH_VOLATILITY"
REGIME_NEUTRAL: str = "NEUTRAL"

# ═══════════════════════════════════════════
# NEWS API
# ═══════════════════════════════════════════
NEWS_MAX_ARTICLES: int = 5
NEWS_LOOKBACK_HOURS: int = 24

# ═══════════════════════════════════════════
# DATABASE
# ═══════════════════════════════════════════
TRADES_HISTORY_LIMIT: int = 10
ANNUALIZED_TRADING_DAYS: int = 252

# ═══════════════════════════════════════════
# SPY/VIX HISTORY — Para screener
# ═══════════════════════════════════════════
SPY_HISTORY_PERIOD: str = "200d"
SPY_SMA_SHORT: int = 50
SPY_SMA_LONG: int = 200
