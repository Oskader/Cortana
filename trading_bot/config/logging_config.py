"""
Configuración de logging estructurado con Loguru.
Separa logs generales, trades, y errores en archivos distintos.
"""

import sys

from loguru import logger

from .settings import settings


def setup_logging() -> None:
    """
    Configura Loguru con handlers para consola, archivo general, y trades.

    Niveles:
        - Console: colored output según LOG_LEVEL
        - logs/bot.log: todos los logs, rotación 50MB, retención 7 días
        - logs/trades.log: solo logs marcados con trade=True, retención 30 días
        - logs/errors.log: solo ERROR+, retención 14 días
    """
    # Remove default handler
    logger.remove()

    # Console handler (colored)
    logger.add(
        sys.stderr,
        level=settings.LOG_LEVEL,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> — "
            "<level>{message}</level>"
        ),
    )

    # General file handler
    logger.add(
        "logs/bot.log",
        rotation="1 day",
        retention="7 days",
        level=settings.LOG_LEVEL,
        compression="zip",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} — {message}",
    )

    # Trade-specific file handler
    logger.add(
        "logs/trades.log",
        filter=lambda record: "trade" in record["extra"],
        rotation="1 day",
        retention="30 days",
        level="INFO",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}",
    )

    # Error-only file handler
    logger.add(
        "logs/errors.log",
        rotation="10 MB",
        retention="14 days",
        level="ERROR",
        compression="zip",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} — {message}",
    )

    logger.info(f"Logging initialized — level: {settings.LOG_LEVEL}")
