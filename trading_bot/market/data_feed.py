"""
WebSocket data feed con reconexión automática y patrón productor-consumidor.

Architecture:
    - Producer: WebSocket handler encola bars ultra-rápido (<1ms)
    - Consumer: Task independiente procesa bars con lógica pesada
    - Reconnection: while-loop con backoff (no recursión)
"""

import asyncio
from typing import Dict, List

from alpaca.data.live import StockDataStream
from loguru import logger

from ..config import constants as C
from ..config.settings import settings
from ..core.state import bot_state


class AlpacaDataStream:
    """
    WebSocket stream con colas asyncio para procesamiento desacoplado.

    Usage (desde engine.py):
        stream = AlpacaDataStream(symbols)
        asyncio.create_task(stream.run())
        asyncio.create_task(stream.consume_bars(callback))
    """

    def __init__(self, symbols: List[str]) -> None:
        self.symbols = symbols
        self._stream: StockDataStream = StockDataStream(
            api_key=settings.ALPACA_API_KEY,
            secret_key=settings.ALPACA_SECRET_KEY,
        )
        self.bar_queue: asyncio.Queue = asyncio.Queue(
            maxsize=C.WEBSOCKET_QUEUE_MAX_SIZE,
        )
        self._is_running: bool = False

    async def _handle_bar(self, bar) -> None:
        """
        WebSocket bar handler — MUST be ultra-fast (<1ms).

        Only enqueues the bar for async processing. Never does heavy
        computation or I/O here.

        Args:
            bar: Alpaca Bar object from the WebSocket.
        """
        # Backpressure: if queue is full, discard oldest bar
        if self.bar_queue.full():
            try:
                self.bar_queue.get_nowait()
                logger.warning(f"Queue full for {bar.symbol}, dropped oldest bar")
            except asyncio.QueueEmpty:
                pass

        await self.bar_queue.put(bar)

    async def run(self) -> None:
        """
        Start the WebSocket stream with automatic reconnection.

        Uses a while-loop instead of recursion to avoid stack overflow.
        Reconnects with configurable delay between attempts.
        """
        self._is_running = True
        logger.info(f"Starting WebSocket stream for {len(self.symbols)} symbols")

        while self._is_running:
            try:
                self._stream = StockDataStream(
                    api_key=settings.ALPACA_API_KEY,
                    secret_key=settings.ALPACA_SECRET_KEY,
                )
                self._stream.subscribe_bars(self._handle_bar, *self.symbols)

                logger.info("WebSocket connected, streaming bars...")
                await self._stream._run_forever()

            except asyncio.CancelledError:
                logger.info("WebSocket stream cancelled")
                break
            except Exception as e:
                logger.error(
                    f"WebSocket disconnected: {e}. "
                    f"Reconnecting in {C.WEBSOCKET_RECONNECT_DELAY_SECONDS}s..."
                )
                await asyncio.sleep(C.WEBSOCKET_RECONNECT_DELAY_SECONDS)

        logger.info("WebSocket stream stopped")

    async def consume_bars(self, callback) -> None:
        """
        Consumer task: dequeues bars and processes them via callback.

        This runs in its own asyncio task, decoupled from the WebSocket
        handler for backpressure management.

        Args:
            callback: Async function to call with each bar.
                      Signature: async def on_bar(bar) -> None
        """
        logger.info("Bar consumer started")
        while True:
            try:
                bar = await self.bar_queue.get()
                logger.debug(f"Processing bar: {bar.symbol} @ {bar.close}")
                await callback(bar)
                self.bar_queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error processing bar: {e}")

    async def stop(self) -> None:
        """Gracefully stop the WebSocket stream."""
        self._is_running = False
        try:
            await self._stream.stop()
        except Exception as e:
            logger.warning(f"Error stopping stream: {e}")
        logger.info("WebSocket stream stop requested")
