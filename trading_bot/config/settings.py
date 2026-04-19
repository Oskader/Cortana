"""
Configuración centralizada del bot usando Pydantic Settings.
Todos los valores se cargan desde variables de entorno o .env file.
"""

import json
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuración principal del bot de trading Cortana."""

    # ═══ ALPACA MARKETS ═══
    ALPACA_API_KEY: str
    ALPACA_SECRET_KEY: str
    ALPACA_BASE_URL: str = "https://paper-api.alpaca.markets"

    # ═══ GROQ AI ═══
    GROQ_API_KEY: str
    GROQ_MODEL: str = "llama-3.3-70b-versatile"
    GROQ_MIN_CONFIDENCE: float = 0.72
    GROQ_TIMEOUT: int = 15
    GROQ_MAX_CONTEXT_TOKENS: int = 8000

    # ═══ TELEGRAM ═══
    TELEGRAM_TOKEN: str
    TELEGRAM_CHAT_ID: int
    ALLOWED_CHAT_IDS: Any = Field(default_factory=list)

    # ═══ NEWS ═══
    NEWS_API_KEY: str = ""

    # ═══ TRADING PARAMETERS ═══
    TRADING_MODE: str = "paper"  # "paper" | "live"
    MAX_DAILY_LOSS_PCT: float = 0.05
    MAX_POSITION_SIZE_PCT: float = 0.20
    MAX_OPEN_POSITIONS: int = 4
    MAX_DAILY_TRADES: int = 3  # PDT-safe limit

    # ═══ SCREENER & STRATEGY ═══
    WATCHLIST_SYMBOLS: Any = [
        "AAPL", "MSFT", "GOOGL", "NVDA", "META",
        "AMZN", "TSLA", "NFLX", "AMD", "COIN",
        "PLTR", "ARM", "MSTR", "SMCI", "QQQ",
        "SPY", "BABA", "PYPL", "SQ", "V"
    ]

    # ═══ MARKET HOURS (ET) ═══
    MARKET_OPEN_HOUR: int = 9
    MARKET_OPEN_MINUTE: int = 35
    MARKET_CLOSE_HOUR: int = 15
    MARKET_CLOSE_MINUTE: int = 50

    # ═══ INFRASTRUCTURE ═══
    DATABASE_URL: str = "sqlite:///data/trading_bot.db"
    LOG_LEVEL: str = "INFO"
    CACHE_TTL_SECONDS: int = 60

    @field_validator("ALLOWED_CHAT_IDS", "WATCHLIST_SYMBOLS", mode="before")
    @classmethod
    def parse_json_or_csv_list(cls, v: object) -> list:
        """
        Parse lists from environment variables.
        Supports JSON arrays ('[1,2,3]') and CSV strings ('a,b,c').
        """
        if isinstance(v, str):
            v = v.strip()
            if not v:
                return []
            try:
                if v.startswith("["):
                    return json.loads(v)
                # Split by comma first, then by space if no commas found
                if "," in v:
                    return [x.strip() for x in v.split(",") if x.strip()]
                return [x.strip() for x in v.split() if x.strip()]
            except (json.JSONDecodeError, ValueError):
                return []
        if isinstance(v, (int, float)):
            return [int(v)]
        return v if v is not None else []

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    def __init__(self, **values: object) -> None:
        super().__init__(**values)
        if not self.ALLOWED_CHAT_IDS:
            self.ALLOWED_CHAT_IDS = [self.TELEGRAM_CHAT_ID]


settings = Settings()
