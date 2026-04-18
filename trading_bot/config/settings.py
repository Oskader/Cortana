from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator
import json

class Settings(BaseSettings):
    # API Keys
    ALPACA_API_KEY: str
    ALPACA_SECRET_KEY: str
    ALPACA_BASE_URL: str = "https://paper-api.alpaca.markets"
    
    GROQ_API_KEY: str
    GROQ_MODEL: str = "llama-3.3-70b-versatile"
    GROQ_MIN_CONFIDENCE: float = 0.72
    
    TELEGRAM_TOKEN: str
    TELEGRAM_CHAT_ID: int
    ALLOWED_CHAT_IDS: List[int] = Field(default_factory=list)

    @field_validator("ALLOWED_CHAT_IDS", mode="before")
    @classmethod
    def parse_chat_ids(cls, v):
        if isinstance(v, str):
            try:
                # Intentar parsear como JSON por si viene "[123, 456]"
                if v.startswith("["):
                    return json.loads(v)
                # Si no, parsear como CSV
                return [int(x.strip()) for x in v.split(",") if x.strip()]
            except:
                return []
        if isinstance(v, int):
            return [v]
        return v
    
    # Trading Parameters
    TRADING_MODE: str = "paper"  # "paper" | "live"
    MAX_DAILY_LOSS_PCT: float = 0.02
    MAX_POSITION_SIZE_PCT: float = 0.05
    MAX_OPEN_POSITIONS: int = 5
    
    # Screener & Strategy
    WATCHLIST_SYMBOLS: List[str] = [
        "AAPL", "MSFT", "GOOGL", "NVDA", "META", "AMZN", "TSLA", "NFLX", "AMD", "COIN"
    ]
    
    # Market Hours (ET)
    MARKET_OPEN_HOUR: int = 9
    MARKET_OPEN_MINUTE: int = 35
    MARKET_CLOSE_HOUR: int = 15
    MARKET_CLOSE_MINUTE: int = 50
    
    # Infrastructure
    DATABASE_URL: str = "sqlite:///trading_bot.db"
    LOG_LEVEL: str = "INFO"
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    def __init__(self, **values):
        super().__init__(**values)
        if not self.ALLOWED_CHAT_IDS:
            self.ALLOWED_CHAT_IDS = [self.TELEGRAM_CHAT_ID]

settings = Settings()
