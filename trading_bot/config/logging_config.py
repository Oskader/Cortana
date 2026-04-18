import sys
from loguru import logger
from .settings import settings

def setup_logging():
    # Remove default handler
    logger.remove()
    
    # Add console handler
    logger.add(
        sys.stderr,
        level=settings.LOG_LEVEL,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
    )
    
    # Add file handler for all logs
    logger.add(
        "logs/bot.log",
        rotation="50 MB",
        retention="7 days",
        level=settings.LOG_LEVEL,
        compression="zip"
    )
    
    # Add separate file handler for trades
    logger.add(
        "logs/trades.log",
        filter=lambda record: "trade" in record["extra"],
        rotation="10 MB",
        retention="30 days",
        level="INFO"
    )

    logger.info(f"Logging initialized with level: {settings.LOG_LEVEL}")
