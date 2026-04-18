import asyncio
from alpaca.data.live import StockDataStream
from loguru import logger
from ..config.settings import settings
from .indicators import TechnicalAnalysis
from ..core.state import bot_state
from typing import Dict, List

class AlpacaDataStream:
    def __init__(self, symbols: List[str]):
        self.symbols = symbols
        self.stream = StockDataStream(
            api_key=settings.ALPACA_API_KEY,
            secret_key=settings.ALPACA_SECRET_KEY
        )
        self.ta = TechnicalAnalysis()
        self.queues: Dict[str, asyncio.Queue] = {s: asyncio.Queue(maxsize=100) for s in symbols}

    async def _handle_bar(self, bar):
        """Procesa una barra en tiempo real"""
        logger.debug(f"Nueva barra recibida: {bar.symbol} @ {bar.close}")
        # Aquí se podría actualizar el bot_state o meter en una cola para procesamiento
        # Por simplicidad en este MVP modular, los handlers irán aquí
        
        # Backpressure check
        if self.queues[bar.symbol].full():
            logger.warning(f"Cola llena para {bar.symbol}, descartando barra antigua")
            await self.queues[bar.symbol].get()
            
        await self.queues[bar.symbol].put(bar)

    async def run(self):
        """Inicia el stream de WebSocket"""
        logger.info(f"Iniciando WebSocket stream para {len(self.symbols)} activos")
        
        try:
            self.stream.subscribe_bars(self._handle_bar, *self.symbols)
            
            # El método run del stream es bloqueante, lo envolvemos en un thread si es necesario
            # pero alpaca-py suele manejarlo bien de forma asíncrona
            await self.stream._run_forever()
        except Exception as e:
            logger.error(f"Error en WebSocket stream: {e}")
            await asyncio.sleep(5)
            await self.run() # Reconexión básica

    def stop(self):
        asyncio.create_task(self.stream.stop())
