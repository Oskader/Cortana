"""
Trade Journal persistente en SQLite con SQLAlchemy.

Registra todas las operaciones y calcula métricas de performance:
- Win rate, profit factor, Sharpe ratio
- Historial reciente para contexto de Groq
- Data para reportes diarios

Nota: Las operaciones son sincrónicas. Se ejecutan dentro de
asyncio.to_thread() desde el engine para no bloquear el event loop.
"""

from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

import numpy as np
from loguru import logger
from sqlalchemy import Column, DateTime, Float, Integer, String, create_engine, func
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from ..config import constants as C
from ..config.settings import settings

Base = declarative_base()


class Trade(Base):
    """Modelo SQLAlchemy de un trade individual."""

    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String, nullable=False)
    side = Column(String, nullable=False)
    qty = Column(Float, nullable=False)
    entry_price = Column(Float, nullable=False)
    exit_price = Column(Float, nullable=True)
    entry_time = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    exit_time = Column(DateTime, nullable=True)
    stop_loss = Column(Float, nullable=True)
    take_profit = Column(Float, nullable=True)
    pnl_dollar = Column(Float, nullable=True)
    pnl_pct = Column(Float, nullable=True)
    confidence_score = Column(Float, nullable=True)
    groq_reasoning = Column(String, nullable=True)
    exit_reason = Column(String, nullable=True)
    market_regime = Column(String, nullable=True)
    order_id = Column(String, nullable=True)


class TradeJournal:
    """
    Interfaz de alto nivel para el trade journal en SQLite.

    Todas las operaciones de escritura/lectura son sincrónicas y deben
    invocarse con asyncio.to_thread() desde código async.
    """

    def __init__(self) -> None:
        self.engine = create_engine(settings.DATABASE_URL, echo=False)
        Base.metadata.create_all(self.engine)
        self._session_factory = sessionmaker(bind=self.engine)
        logger.info(f"Trade journal initialized: {settings.DATABASE_URL}")

    def _get_session(self) -> Session:
        """Create a new database session."""
        return self._session_factory()

    # ═══════════════════════════════════════
    # WRITE OPERATIONS
    # ═══════════════════════════════════════

    def log_entry(self, **kwargs: Any) -> int:
        """
        Log a new trade entry.

        Args:
            **kwargs: Fields matching the Trade model columns.

        Returns:
            Database ID of the new trade, or -1 on error.
        """
        session = self._get_session()
        try:
            trade = Trade(**kwargs)
            session.add(trade)
            session.commit()
            trade_id = trade.id
            logger.info(
                f"Trade logged: ID={trade_id}, "
                f"{kwargs.get('side')} {kwargs.get('ticker')} "
                f"x{kwargs.get('qty')}",
                trade=True,
            )
            return trade_id
        except Exception as e:
            session.rollback()
            logger.error(f"Error logging trade entry: {e}")
            return -1
        finally:
            session.close()

    def log_exit(
        self,
        trade_id: int,
        exit_price: float,
        exit_reason: str,
    ) -> None:
        """
        Log a trade exit with P&L calculation.

        Args:
            trade_id: Database ID of the trade.
            exit_price: Exit price achieved.
            exit_reason: Reason for exit (STOP_LOSS, TAKE_PROFIT, MANUAL, etc).
        """
        session = self._get_session()
        try:
            trade = session.query(Trade).filter(Trade.id == trade_id).first()
            if trade is None:
                logger.error(f"Trade ID {trade_id} not found for exit logging")
                return

            trade.exit_price = exit_price
            trade.exit_time = datetime.now(timezone.utc)
            trade.exit_reason = exit_reason

            # P&L calculation based on side
            if trade.side == "BUY":
                trade.pnl_dollar = (exit_price - trade.entry_price) * trade.qty
            else:  # SELL (short)
                trade.pnl_dollar = (trade.entry_price - exit_price) * trade.qty

            if trade.entry_price > 0 and trade.qty > 0:
                trade.pnl_pct = trade.pnl_dollar / (trade.entry_price * trade.qty)

            session.commit()
            logger.info(
                f"Trade {trade_id} closed: {exit_reason}, "
                f"P&L=${trade.pnl_dollar:+.2f} ({trade.pnl_pct:+.2%})",
                trade=True,
            )
        except Exception as e:
            session.rollback()
            logger.error(f"Error logging trade exit: {e}")
        finally:
            session.close()

    # ═══════════════════════════════════════
    # READ OPERATIONS
    # ═══════════════════════════════════════

    def get_basic_stats(self) -> Dict[str, Any]:
        """
        Get basic trading statistics for Kelly calculation.

        Returns:
            Dict with win_rate, total_pnl, trades count, avg_win, avg_loss.
        """
        session = self._get_session()
        try:
            closed_trades = (
                session.query(Trade)
                .filter(Trade.exit_price.isnot(None))
                .all()
            )

            if not closed_trades:
                return {
                    "win_rate": 0.5,
                    "total_pnl": 0.0,
                    "trades": 0,
                    "avg_win": 2.0,
                    "avg_loss": 1.0,
                }

            wins = [t for t in closed_trades if (t.pnl_dollar or 0) > 0]
            losses = [t for t in closed_trades if (t.pnl_dollar or 0) < 0]
            total = len(closed_trades)

            win_rate = len(wins) / total if total > 0 else 0.5
            total_pnl = sum(t.pnl_dollar or 0 for t in closed_trades)
            avg_win = (
                sum(t.pnl_dollar for t in wins) / len(wins)
                if wins else 2.0
            )
            avg_loss = (
                abs(sum(t.pnl_dollar for t in losses)) / len(losses)
                if losses else 1.0
            )

            return {
                "win_rate": win_rate,
                "total_pnl": total_pnl,
                "trades": total,
                "avg_win": avg_win,
                "avg_loss": avg_loss,
            }
        finally:
            session.close()

    def get_performance_metrics(self) -> Dict[str, Any]:
        """
        Calculate advanced performance metrics.

        Returns:
            Dict with sharpe_ratio, profit_factor, max_drawdown_pct,
            win_rate, total_trades, total_pnl.
        """
        session = self._get_session()
        try:
            trades = (
                session.query(Trade)
                .filter(Trade.exit_price.isnot(None))
                .order_by(Trade.exit_time)
                .all()
            )

            empty_metrics = {
                "sharpe_ratio": 0.0,
                "profit_factor": 0.0,
                "max_drawdown_pct": 0.0,
                "win_rate": 0.0,
                "total_trades": 0,
                "total_pnl": 0.0,
            }

            if not trades:
                return empty_metrics

            pnls = [t.pnl_dollar or 0 for t in trades]
            wins_pnl = [p for p in pnls if p > 0]
            losses_pnl = [abs(p) for p in pnls if p < 0]

            # Sharpe Ratio (annualized)
            sharpe = 0.0
            if len(pnls) > 1:
                returns_array = np.array(pnls)
                mean_return = float(np.mean(returns_array))
                std_return = float(np.std(returns_array, ddof=1))
                if std_return > 0:
                    sharpe = (mean_return / std_return) * np.sqrt(C.ANNUALIZED_TRADING_DAYS)

            # Profit Factor
            gross_profit = sum(wins_pnl) if wins_pnl else 0
            gross_loss = sum(losses_pnl) if losses_pnl else 1
            profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0.0

            # Max Drawdown
            cumulative = np.cumsum(pnls)
            peak = np.maximum.accumulate(cumulative)
            drawdowns = peak - cumulative
            max_dd = float(np.max(drawdowns)) if len(drawdowns) > 0 else 0
            peak_val = float(peak[np.argmax(drawdowns)]) if len(drawdowns) > 0 and max_dd > 0 else 1
            max_dd_pct = max_dd / peak_val if peak_val > 0 else 0

            return {
                "sharpe_ratio": round(float(sharpe), 2),
                "profit_factor": round(profit_factor, 2),
                "max_drawdown_pct": round(max_dd_pct, 4),
                "win_rate": round(len(wins_pnl) / len(trades), 4),
                "total_trades": len(trades),
                "total_pnl": round(sum(pnls), 2),
            }
        finally:
            session.close()

    def get_recent_trades(
        self,
        limit: int = C.TRADES_HISTORY_LIMIT,
    ) -> List[Dict[str, Any]]:
        """
        Get recent closed trades for Groq context.

        Args:
            limit: Maximum number of trades to return.

        Returns:
            List of trade dicts in chronological order.
        """
        session = self._get_session()
        try:
            trades = (
                session.query(Trade)
                .filter(Trade.exit_price.isnot(None))
                .order_by(Trade.exit_time.desc())
                .limit(limit)
                .all()
            )
            return [
                {
                    "ticker": t.ticker,
                    "side": t.side,
                    "pnl_dollar": t.pnl_dollar or 0,
                    "pnl_pct": t.pnl_pct or 0,
                    "exit_reason": t.exit_reason or "N/A",
                }
                for t in reversed(trades)  # Chronological order
            ]
        finally:
            session.close()

    def get_daily_summary(
        self,
        target_date: Optional[date] = None,
    ) -> Dict[str, Any]:
        """
        Get summary of all trades for a specific date.

        Args:
            target_date: Date to summarize (defaults to today).

        Returns:
            Dict with trades_count, total_pnl, wins, losses.
        """
        session = self._get_session()
        try:
            if target_date is None:
                target_date = date.today()

            trades = (
                session.query(Trade)
                .filter(func.date(Trade.entry_time) == target_date)
                .all()
            )

            closed = [t for t in trades if t.exit_price is not None]
            pnls = [t.pnl_dollar or 0 for t in closed]

            return {
                "date": target_date.isoformat(),
                "total_trades": len(trades),
                "closed_trades": len(closed),
                "open_trades": len(trades) - len(closed),
                "total_pnl": sum(pnls),
                "wins": len([p for p in pnls if p > 0]),
                "losses": len([p for p in pnls if p < 0]),
                "best_trade": max(pnls) if pnls else 0,
                "worst_trade": min(pnls) if pnls else 0,
            }
        finally:
            session.close()
