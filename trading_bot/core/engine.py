import asyncio
from loguru import logger
from ..config.settings import settings
from ..core.state import bot_state, PositionState
from ..execution.alpaca_client import AlpacaClient
from ..brain.groq_agent import GroqAgent
from ..risk.risk_manager import RiskManager
from ..risk.portfolio_sizer import PortfolioSizer
from ..market.data_feed import AlpacaDataStream
from ..telegram.bot import TelegramUI
from ..market.indicators import TechnicalAnalysis
import pandas as pd
from ..market.screener import Screener
from ..utils.db import TradeJournal
from alpaca.trading.enums import OrderSide

class TradingEngine:
    def __init__(self):
        self.alpaca = AlpacaClient()
        self.brain = GroqAgent()
        self.risk = RiskManager()
        self.sizer = PortfolioSizer()
        self.tg = TelegramUI()
        self.ta = TechnicalAnalysis()
        self.stream = AlpacaDataStream(settings.WATCHLIST_SYMBOLS)
        self.screener = Screener()
        self.journal = TradeJournal()

    async def update_state_loop(self):
        """Mantiene el estado global actualizado (Account + Positions)"""
        while True:
            try:
                # Usar to_thread para no bloquear el event loop con llamadas síncronas
                acc = await asyncio.to_thread(self.alpaca.get_account_info)
                await bot_state.update_account(
                    balance=float(acc.cash),
                    equity=float(acc.portfolio_value),
                    buying_power=float(acc.buying_power)
                )
                
                # Sincronizar posiciones
                alp_positions = await asyncio.to_thread(self.alpaca.get_positions)
                pos_list = []
                for p in alp_positions:
                    pos_list.append(PositionState(
                        symbol=p.symbol,
                        qty=float(p.qty),
                        entry_price=float(p.avg_entry_price),
                        current_price=float(p.current_price),
                        unrealized_pnl=float(p.unrealized_pl),
                        unrealized_pnl_pct=float(p.unrealized_plpc)
                    ))
                await bot_state.update_positions(pos_list)
                
            except Exception as e:
                logger.error(f"Error actualizando estado en engine: {e}")
            
            await asyncio.sleep(60) # Actualizar cada minuto

    async def scan_market_loop(self):
        """Escanea la watchlist periódicamente para buscar oportunidades"""
        while True:
            if not bot_state.is_running:
                await asyncio.sleep(60)
                continue
                
            # 0. Detectar Régimen de Mercado
            regime = await asyncio.to_thread(self.screener.get_market_regime)
            await bot_state.set_market_regime(regime)
            logger.info(f"Régimen de mercado detectado: {regime}")

            logger.info("Iniciando escaneo de mercado...")
            
            for symbol in settings.WATCHLIST_SYMBOLS:
                try:
                    # 1. Obtener datos históricos
                    df = await asyncio.to_thread(self.alpaca.get_historical_bars, symbol, "1Hour", 100)
                    if df is None or df.empty: continue
                    
                    # 2. Calcular indicadores
                    df = self.ta.calculate_indicators(df)
                    score = self.ta.get_signal_score(df)
                    
                    logger.debug(f"{symbol} Signal Score: {score}")
                    
                    # 3. Filtrar por score inicial (Criterio de Mejora 4.2)
                    if score >= 70:
                        logger.info(f"Señal FUERTE detectada para {symbol} ({score} pts). Consultando cerebro...")
                        await self.process_opportunity(symbol, df, score)
                    elif score >= 50:
                        logger.info(f"Señal moderada para {symbol} ({score} pts).")
                        # Aquí podrías decidir si procesar o no basado en otras condiciones
                
                except Exception as e:
                    logger.error(f"Error escaneando {symbol}: {e}")
                    
                await asyncio.sleep(2) # Rate limiting entre tickers

            await asyncio.sleep(300) # Escaneo cada 5 min

    async def process_opportunity(self, symbol: str, df: pd.DataFrame, score: int):
        """Orquestación completa: Cerebro -> Riesgo -> Ejecución"""
        
        # 1. Construir contexto para Groq
        last_data = df.iloc[-1].to_dict()
        context = f"""
        Ticker: {symbol}
        Score Técnico: {score}/100
        Precio: ${last_data['close']}
        RSI: {last_data['RSI']:.2f}
        ATR: {last_data['ATR']:.2f}
        Rel Volume: {last_data['REL_VOL']:.2f}
        Market Regime: {bot_state.market_regime}
        Equity: ${bot_state.equity:,.2f}
        """
        
        # 2. Consultar Groq (Reflection Pattern)
        decision = await self.brain.analyze_with_reflection(context)
        
        if decision.get("action") == "BUY" and decision.get("confidence", 0) >= settings.GROQ_MIN_CONFIDENCE:
            # 3. Position Sizing
            qty = self.sizer.get_quantity(symbol, last_data['close'])
            decision["qty"] = qty
            
            # 4. Risk Validation
            if await self.risk.validate_trade(decision):
                # 5. Ejecución
                try:
                    order = await asyncio.to_thread(self.alpaca.submit_order, symbol, qty, OrderSide.BUY)
                    logger.success(f"ORDEN EJECUTADA: BUY {qty} {symbol}")
                    
                    # 6. Notificación
                    await self.tg.send_alert(f"🟩 <b>COMPRA EJECUTADA</b>\n{symbol} - {qty} shares @ ${last_data['close']}")
                except Exception as e:
                    logger.error(f"Error ejecutando orden para {symbol}: {e}")

    async def run(self):
        """Inicia todos los componentes del motor"""
        logger.info("Encendiendo motores de Cortana Bot...")
        
        # Inicializar Telegram
        asyncio.create_task(self.tg.run())
        
        # Iniciar loops de fondo
        tasks = [
            self.update_state_loop(),
            self.scan_market_loop(),
            # self.stream.run() # WebSocket habilitado después de validar el core
        ]
        
        await self.tg.send_alert("✨ <b>Cortana v5 ha iniciado sesión</b>\nProtocolos activos en modo " + settings.TRADING_MODE.upper())
        await asyncio.gather(*tasks)
