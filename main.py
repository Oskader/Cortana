"""
Cortana Trading Bot — Entry Point.

Institucional-grade algorithmic trading bot powered by:
    - Alpaca Markets (execution + market data)
    - Groq AI (analysis with Reflection Pattern)
    - Telegram (interface + notifications)
"""

import asyncio
import sys

import portalocker
from loguru import logger

try:
    from trading_bot.config.logging_config import setup_logging
    from trading_bot.core.engine import TradingEngine
except ImportError as e:
    print(f"CRITICAL: Error al importar módulos: {e}")
    sys.exit(1)
except Exception as e:
    print(f"CRITICAL: Error de configuración (posiblemente faltan variables en .env): {e}")
    sys.exit(1)


async def main() -> None:
    """Initialize and run the trading engine."""
    setup_logging()

    logger.info("═══ CORTANA BOT — INICIANDO ═══")

    # Prevent multiple instances running concurrently
    lock_file = open("cortana_bot.lock", "w")
    try:
        portalocker.lock(lock_file, portalocker.LOCK_EX | portalocker.LOCK_NB)
    except portalocker.exceptions.LockException:
        logger.critical("FATAL ERROR: Otra instancia de Cortana ya está ejecutándose.")
        sys.exit(1)

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
        finally:
            try:
                portalocker.unlock(lock_file)
                lock_file.close()
            except Exception:
                pass
        logger.info("═══ CORTANA BOT — APAGADO ═══")


if __name__ == "__main__":
    try:
        if sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
