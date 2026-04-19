"""
Cortana Trading Bot — Entry Point.

Institucional-grade algorithmic trading bot powered by:
    - Alpaca Markets (execution + market data)
    - Groq AI (analysis with Reflection Pattern)
    - Telegram (interface + notifications)
"""

import asyncio
import sys

from loguru import logger

from trading_bot.config.logging_config import setup_logging
from trading_bot.core.engine import TradingEngine


async def main() -> None:
    """Initialize and run the trading engine."""
    setup_logging()

    logger.info("═══ CORTANA BOT — INICIANDO ═══")

    engine = TradingEngine()

    try:
        await engine.run()
    except KeyboardInterrupt:
        logger.warning("Manual shutdown detected (Ctrl+C)")
    except Exception as e:
        logger.critical(f"FATAL ERROR: {type(e).__name__}: {e}")
        sys.exit(1)
    finally:
        try:
            await engine.shutdown()
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")
        logger.info("═══ CORTANA BOT — APAGADO ═══")


if __name__ == "__main__":
    try:
        if sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
