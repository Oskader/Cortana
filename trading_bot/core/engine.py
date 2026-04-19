"""
Motor de trading principal — orquesta todos los componentes.

Responsabilidades (SRP via métodos separados):
    - update_state_loop: sincroniza account/positions con Alpaca cada 60s
    - scan_market_loop: escanea watchlist cada 5min buscando oportunidades
    - process_opportunity: flujo completo señal → riesgo → ejecución → log
    - on_realtime_bar: procesa bars del WebSocket para monitoring

Arquitectura:
    Todos los componentes son inyectados en __init__.
    Las llamadas sync se ejecutan en asyncio.to_thread().
    Las tareas independientes corren en paralelo con asyncio.gather().
"""

import asyncio
import os
from typing import Optional

import pandas as pd
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.enums import OrderSide
from loguru import logger

from ..brain.groq_agent import GroqAgent, GroqTradeSignal, fetch_news_for_ticker
from ..config import constants as C
from ..config.settings import settings
from ..core.state import PositionState, bot_state
from ..execution.alpaca_client import AlpacaClient
from ..market.cache import MarketDataCache
from ..market.data_feed import AlpacaDataStream
from ..market.indicators import TechnicalAnalysis
from ..market.screener import Screener
from ..risk.portfolio_sizer import PortfolioSizer
from ..risk.risk_manager import RiskManager
from ..telegram.bot import TelegramUI
from ..utils.db import TradeJournal


class TradingEngine:
    """
    Motor central de trading — orquesta el flujo completo.

    Lifecycle:
        engine = TradingEngine()
        await engine.run()  # Starts all loops and components
    """

    def __init__(self) -> None:
        # Execution
        self.alpaca = AlpacaClient()

        # Intelligence
        self.brain = GroqAgent()
        self.ta = TechnicalAnalysis()
        self.screener = Screener()

        # Risk
        self.risk = RiskManager()
        self.sizer = PortfolioSizer()

        # Data
        self.stream = AlpacaDataStream(settings.WATCHLIST_SYMBOLS)
        self.cache = MarketDataCache(ttl_seconds=settings.CACHE_TTL_SECONDS)

        # Persistence
        self.journal = TradeJournal()

        # Interface
        self.tg = TelegramUI()
        self.tg.set_journal(self.journal)

        # Task references (prevent GC)
        self._tasks: list[asyncio.Task] = []

    # ═══════════════════════════════════════
    # LIFECYCLE
    # ═══════════════════════════════════════

    async def run(self) -> None:
        """Start all engine components and background loops."""
        logger.info("🚀 Starting Cortana Trading Engine...")

        # Ensure data directory exists
        os.makedirs("data", exist_ok=True)
        os.makedirs("logs", exist_ok=True)

        # Initialize Kelly stats from journal
        await self._update_kelly_stats()

        # Start Telegram (as background task)
        tg_task = asyncio.create_task(self.tg.run())
        self._tasks.append(tg_task)

        # Start WebSocket stream (background)
        ws_task = asyncio.create_task(self.stream.run())
        self._tasks.append(ws_task)

        # Start bar consumer (background)
        consumer_task = asyncio.create_task(
            self.stream.consume_bars(self._on_realtime_bar)
        )
        self._tasks.append(consumer_task)

        # Send startup notification
        mode = settings.TRADING_MODE.upper()
        await self.tg.send_alert(
            f"✨ <b>Cortana v5 ha iniciado sesión</b>\n"
            f"Protocolos activos en modo <code>{mode}</code>\n"
            f"Watchlist: {len(settings.WATCHLIST_SYMBOLS)} activos\n"
            f"WebSocket: ✅ Activo"
        )

        # Run main loops
        await asyncio.gather(
            self._update_state_loop(),
            self._scan_market_loop(),
        )

    async def shutdown(self) -> None:
        """Gracefully shutdown all components."""
        logger.info("Shutting down Cortana Engine...")
        await self.stream.stop()
        await self.tg.stop()
        for task in self._tasks:
            task.cancel()
        logger.info("Engine shutdown complete")

    # ═══════════════════════════════════════
    # STATE SYNCHRONIZATION LOOP
    # ═══════════════════════════════════════

    async def _update_state_loop(self) -> None:
        """Sync account info and positions with Alpaca every 60s."""
        while True:
            try:
                await self._sync_account()
                await self._sync_positions()
            except Exception as e:
                logger.error(f"Error updating state: {e}")

            await asyncio.sleep(C.STATE_UPDATE_INTERVAL_SECONDS)

    async def _sync_account(self) -> None:
        """Fetch account info from Alpaca and update global state."""
        acc = await asyncio.to_thread(self.alpaca.get_account_info)
        await bot_state.update_account(
            balance=float(acc.cash),
            equity=float(acc.portfolio_value),
            buying_power=float(acc.buying_power),
        )

    async def _sync_positions(self) -> None:
        """Fetch positions from Alpaca and update global state."""
        alp_positions = await asyncio.to_thread(self.alpaca.get_positions)
        positions = [
            PositionState(
                symbol=p.symbol,
                qty=float(p.qty),
                entry_price=float(p.avg_entry_price),
                current_price=float(p.current_price),
                unrealized_pnl=float(p.unrealized_pl),
                unrealized_pnl_pct=float(p.unrealized_plpc),
            )
            for p in alp_positions
        ]
        await bot_state.update_positions(positions)

    # ═══════════════════════════════════════
    # MARKET SCANNING LOOP
    # ═══════════════════════════════════════

    async def _scan_market_loop(self) -> None:
        """Scan the watchlist periodically for trading opportunities."""
        while True:
            if not bot_state.is_running:
                await asyncio.sleep(C.STATE_UPDATE_INTERVAL_SECONDS)
                continue

            try:
                await self._run_scan_cycle()
            except Exception as e:
                logger.error(f"Error in scan cycle: {e}")

            await asyncio.sleep(C.SCAN_INTERVAL_SECONDS)

    async def _run_scan_cycle(self) -> None:
        """Execute one full scan cycle: regime detection + symbol scanning."""
        # Detect market regime
        regime = await asyncio.to_thread(self.screener.get_market_regime)
        await bot_state.set_market_regime(regime)
        logger.info(f"Market regime: {regime}")

        # Update Kelly stats periodically
        await self._update_kelly_stats()

        # Scan watchlist
        logger.info(f"Scanning {len(settings.WATCHLIST_SYMBOLS)} symbols...")
        for symbol in settings.WATCHLIST_SYMBOLS:
            await self._analyze_symbol(symbol)
            await asyncio.sleep(C.SCAN_TICKER_DELAY_SECONDS)

    async def _analyze_symbol(self, symbol: str) -> None:
        """
        Analyze a single symbol: fetch data → indicators → score → trade.

        Args:
            symbol: Stock ticker to analyze.
        """
        try:
            # Check cache first
            cache_key = f"{symbol}_1h"
            cached_df = self.cache.get(cache_key)

            if cached_df is not None:
                df = cached_df
            else:
                df = await asyncio.to_thread(
                    self.alpaca.get_historical_bars,
                    symbol, TimeFrame.Hour, C.DEFAULT_BAR_LIMIT,
                )
                if df is not None and not df.empty:
                    self.cache.set(cache_key, df)

            if df is None or df.empty:
                return

            # Calculate indicators in thread pool (CPU-bound)
            df = await asyncio.get_event_loop().run_in_executor(
                None, self.ta.calculate_indicators, df,
            )

            score = self.ta.get_signal_score(df)
            logger.debug(f"{symbol} → Score: {score}/100")

            # Process if strong signal
            if score >= C.SCORE_STRONG_SIGNAL:
                logger.info(
                    f"🎯 STRONG signal: {symbol} ({score}pts). "
                    f"Starting analysis..."
                )
                await self._process_opportunity(symbol, df, score)
            elif score >= C.SCORE_MODERATE_SIGNAL:
                logger.info(f"📊 Moderate signal: {symbol} ({score}pts)")

        except Exception as e:
            logger.error(f"Error analyzing {symbol}: {e}")

    # ═══════════════════════════════════════
    # TRADE PROCESSING FLOW
    # ═══════════════════════════════════════

    async def _process_opportunity(
        self,
        symbol: str,
        df: pd.DataFrame,
        score: int,
    ) -> None:
        """
        Complete trade flow: AI Analysis → Risk → Execution → Log → Notify.

        Args:
            symbol: Ticker symbol.
            df: DataFrame with calculated indicators.
            score: Signal score (0-100).
        """
        # 1. Build context for Groq
        context = await self._build_groq_context(symbol, df, score)

        # 2. AI Analysis (Reflection Pattern: 3 Groq calls)
        signal = await self.brain.analyze_with_reflection(context)

        if signal is None or signal.action == "HOLD":
            logger.info(f"{symbol}: AI decision → HOLD. Skipping.")
            return

        if signal.confidence < settings.GROQ_MIN_CONFIDENCE:
            logger.info(
                f"{symbol}: Confidence {signal.confidence:.2f} < "
                f"minimum {settings.GROQ_MIN_CONFIDENCE}. Skipping."
            )
            return

        # Only process BUY signals (no short selling)
        if signal.action != "BUY":
            logger.info(f"{symbol}: Action={signal.action}, only BUY supported.")
            return

        # 3. Position Sizing
        qty = self.sizer.get_quantity(
            ticker=symbol,
            entry_price=signal.entry_price_target,
            market_regime=bot_state.market_regime,
        )
        if qty <= 0:
            logger.warning(f"{symbol}: Calculated qty=0. Skipping.")
            return

        # 4. Risk Validation (9-point checklist)
        estimated_cost = qty * signal.entry_price_target
        is_valid, reason = await self.risk.validate_trade(signal, estimated_cost)

        if not is_valid:
            await self.tg.send_alert(
                f"🚫 <b>Trade bloqueado</b>\n"
                f"{symbol}: {reason}"
            )
            return

        # 5. Execute Bracket Order
        await self._execute_trade(signal, qty)

    async def _build_groq_context(
        self,
        symbol: str,
        df: pd.DataFrame,
        score: int,
    ) -> str:
        """Build complete context for Groq analysis."""
        last_data = df.iloc[-1].to_dict()

        # Fetch news in parallel with getting recent trades
        news_task = asyncio.create_task(fetch_news_for_ticker(symbol))
        recent_trades = await asyncio.to_thread(self.journal.get_recent_trades)
        news = await news_task

        account_info = {
            "equity": bot_state.equity,
            "buying_power": bot_state.buying_power,
            "daily_pnl_pct": bot_state.daily_pnl_pct,
            "position_count": bot_state.open_position_count,
        }

        return await self.brain.build_context(
            ticker=symbol,
            score=score,
            indicators=last_data,
            account_info=account_info,
            market_regime=bot_state.market_regime,
            recent_trades=recent_trades,
            news=news,
        )

    async def _execute_trade(
        self,
        signal: GroqTradeSignal,
        qty: int,
    ) -> None:
        """
        Execute the bracket order and log to journal + Telegram.

        Args:
            signal: Validated trade signal.
            qty: Number of shares to trade.
        """
        try:
            order = await asyncio.to_thread(
                self.alpaca.submit_bracket_order,
                symbol=signal.ticker,
                qty=qty,
                side=OrderSide.BUY,
                stop_loss_price=signal.stop_loss,
                take_profit_price=signal.take_profit,
            )

            logger.success(
                f"ORDER EXECUTED: BUY {qty} {signal.ticker} "
                f"(order_id={order.id})",
                trade=True,
            )

            # Log to journal
            await asyncio.to_thread(
                self.journal.log_entry,
                ticker=signal.ticker,
                side="BUY",
                qty=qty,
                entry_price=signal.entry_price_target,
                stop_loss=signal.stop_loss,
                take_profit=signal.take_profit,
                confidence_score=signal.confidence,
                groq_reasoning=signal.reasoning,
                market_regime=bot_state.market_regime,
                order_id=str(order.id),
            )

            # Update trade counter
            await bot_state.increment_trades_today()

            # Notify via Telegram
            await self.tg.send_trade_alert(
                ticker=signal.ticker,
                side="BUY",
                qty=qty,
                price=signal.entry_price_target,
                stop_loss=signal.stop_loss,
                take_profit=signal.take_profit,
                confidence=signal.confidence,
                reasoning=signal.reasoning,
            )

        except Exception as e:
            logger.error(f"Trade execution failed for {signal.ticker}: {e}")
            await self.tg.send_alert(
                f"❌ <b>Error ejecutando trade</b>\n"
                f"{signal.ticker}: {str(e)}"
            )

    # ═══════════════════════════════════════
    # REALTIME BAR PROCESSING
    # ═══════════════════════════════════════

    async def _on_realtime_bar(self, bar) -> None:
        """
        Process a real-time bar from the WebSocket.

        Used for monitoring open positions. The actual trading decisions
        are made in the scan loop, not here.

        Args:
            bar: Alpaca Bar object from WebSocket.
        """
        symbol = bar.symbol

        # Update cache with latest price
        if bot_state.has_position(symbol):
            logger.debug(
                f"RT bar: {symbol} @ ${bar.close} "
                f"(vol={bar.volume})"
            )

    # ═══════════════════════════════════════
    # KELLY STATS UPDATE
    # ═══════════════════════════════════════

    async def _update_kelly_stats(self) -> None:
        """Update the portfolio sizer with real statistics from the journal."""
        try:
            stats = await asyncio.to_thread(self.journal.get_basic_stats)
            self.sizer.update_stats_from_journal(stats)
        except Exception as e:
            logger.warning(f"Error updating Kelly stats: {e}")
