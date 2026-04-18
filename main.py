import asyncio
import sys
from loguru import logger
from trading_bot.config.logging_config import setup_logging
from trading_bot.core.engine import TradingEngine

async def main():
    # 1. Configurar Logging
    setup_logging()
    
    logger.info("Iniciando aplicación Cortana Bot...")
    
    try:
        # 2. Inicializar el motor
        engine = TradingEngine()
        
        # 3. Correr el bot
        await engine.run()
        
    except KeyboardInterrupt:
        logger.warning("Detención manual detectada...")
    except Exception as e:
        logger.critical(f"ERROR CRÍTICO EN MAIN: {e}")
        sys.exit(1)
    finally:
        logger.info("Bot apagado correctamente.")

if __name__ == "__main__":
    try:
        if sys.platform == 'win32':
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
