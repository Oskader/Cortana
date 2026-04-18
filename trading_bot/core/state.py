import asyncio
from typing import Dict, List, Optional
from datetime import datetime
from pydantic import BaseModel

class PositionState(BaseModel):
    symbol: str
    qty: float
    entry_price: float
    current_price: float
    unrealized_pnl: float
    unrealized_pnl_pct: float
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None

class GlobalState:
    def __init__(self):
        self._lock = asyncio.Lock()
        self.balance: float = 0.0
        self.equity: float = 0.0
        self.buying_power: float = 0.0
        self.positions: Dict[str, PositionState] = {}
        self.is_running: bool = True
        self.daily_pnl: float = 0.0
        self.daily_pnl_pct: float = 0.0
        self.max_drawdown: float = 0.0
        self.market_regime: str = "NEUTRAL"
        self.last_update: datetime = datetime.now()

    async def update_account(self, balance: float, equity: float, buying_power: float):
        async with self._lock:
            self.balance = balance
            self.equity = equity
            self.buying_power = buying_power
            self.last_update = datetime.now()

    async def update_positions(self, positions_list: List[PositionState]):
        async with self._lock:
            self.positions = {p.symbol: p for p in positions_list}
            self.last_update = datetime.now()

    async def set_market_regime(self, regime: str):
        async with self._lock:
            self.market_regime = regime

    async def toggle_running(self, status: bool):
        async with self._lock:
            self.is_running = status

bot_state = GlobalState()
