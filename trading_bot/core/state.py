"""
Estado global del bot con sincronización thread-safe via asyncio.Lock.
Tracking completo de P&L diario, drawdown máximo, y régimen de mercado.
"""

import asyncio
from datetime import date, datetime, timezone
from typing import Dict, List, Optional

from pydantic import BaseModel

from ..config.constants import REGIME_NEUTRAL


class PositionState(BaseModel):
    """Snapshot inmutable de una posición abierta."""

    symbol: str
    qty: float
    entry_price: float
    current_price: float
    unrealized_pnl: float
    unrealized_pnl_pct: float
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None


class GlobalState:
    """
    Estado global singleton del bot, protegido por asyncio.Lock.

    Responsabilidades:
        - Tracking de account info (balance, equity, buying power)
        - Tracking de posiciones abiertas
        - Cálculo de P&L diario y drawdown máximo
        - Conteo de trades diarios (PDT protection)
        - Estado de ejecución del bot (running/paused)
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()

        # Account
        self.balance: float = 0.0
        self.equity: float = 0.0
        self.buying_power: float = 0.0

        # Positions
        self.positions: Dict[str, PositionState] = {}

        # Runtime
        self.is_running: bool = True
        self.market_regime: str = REGIME_NEUTRAL
        self.last_update: datetime = datetime.now(timezone.utc)

        # Daily P&L tracking
        self._start_of_day_equity: float = 0.0
        self._current_date: date = date.today()
        self.daily_pnl: float = 0.0
        self.daily_pnl_pct: float = 0.0

        # Drawdown tracking
        self.peak_equity: float = 0.0
        self.max_drawdown: float = 0.0

        # Trade counter (PDT protection)
        self.trades_today: int = 0

    async def update_account(
        self,
        balance: float,
        equity: float,
        buying_power: float,
    ) -> None:
        """
        Update account info and recalculate daily P&L + drawdown.

        Args:
            balance: Cash balance in USD.
            equity: Total portfolio value in USD.
            buying_power: Available buying power in USD.
        """
        async with self._lock:
            self.balance = balance
            self.equity = equity
            self.buying_power = buying_power
            self.last_update = datetime.now(timezone.utc)

            # Reset daily tracking on new day
            today = date.today()
            if today != self._current_date:
                self._start_of_day_equity = equity
                self._current_date = today
                self.trades_today = 0

            # Initialize start-of-day equity on first update
            if self._start_of_day_equity <= 0:
                self._start_of_day_equity = equity

            # Daily P&L calculation
            self.daily_pnl = equity - self._start_of_day_equity
            if self._start_of_day_equity > 0:
                self.daily_pnl_pct = self.daily_pnl / self._start_of_day_equity
            else:
                self.daily_pnl_pct = 0.0

            # Drawdown tracking (high-water mark)
            if equity > self.peak_equity:
                self.peak_equity = equity
            if self.peak_equity > 0:
                current_drawdown = (self.peak_equity - equity) / self.peak_equity
                self.max_drawdown = max(self.max_drawdown, current_drawdown)

    async def update_positions(self, positions_list: List[PositionState]) -> None:
        """
        Replace the current positions snapshot.

        Args:
            positions_list: List of current positions from the broker.
        """
        async with self._lock:
            self.positions = {p.symbol: p for p in positions_list}
            self.last_update = datetime.now(timezone.utc)

    async def set_market_regime(self, regime: str) -> None:
        """
        Update the detected market regime.

        Args:
            regime: One of the REGIME_* constants.
        """
        async with self._lock:
            self.market_regime = regime

    async def toggle_running(self, status: bool) -> None:
        """
        Pause or resume the trading engine.

        Args:
            status: True to run, False to pause.
        """
        async with self._lock:
            self.is_running = status

    async def increment_trades_today(self) -> None:
        """Increment the daily trade counter for PDT protection."""
        async with self._lock:
            self.trades_today += 1

    @property
    def open_position_count(self) -> int:
        """Number of currently open positions."""
        return len(self.positions)

    def has_position(self, symbol: str) -> bool:
        """Check if there's an open position for a given symbol."""
        return symbol in self.positions


bot_state = GlobalState()
