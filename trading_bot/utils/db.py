from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
from ..config.settings import settings

Base = declarative_base()

class Trade(Base):
    __tablename__ = 'trades'
    id = Column(Integer, primary_key=True)
    ticker = Column(String)
    side = Column(String)
    qty = Column(Float)
    entry_price = Column(Float)
    exit_price = Column(Float)
    entry_time = Column(DateTime, default=datetime.now)
    exit_time = Column(DateTime)
    stop_loss = Column(Float)
    take_profit = Column(Float)
    pnl_dollar = Column(Float)
    pnl_pct = Column(Float)
    confidence_score = Column(Float)
    groq_reasoning = Column(String)
    exit_reason = Column(String)
    market_regime = Column(String)

class TradeJournal:
    def __init__(self):
        self.engine = create_engine(settings.DATABASE_URL)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def log_entry(self, **kwargs):
        session = self.Session()
        new_trade = Trade(**kwargs)
        session.add(new_trade)
        session.commit()
        trade_id = new_trade.id
        session.close()
        return trade_id

    def log_exit(self, trade_id, exit_price, exit_reason):
        session = self.Session()
        trade = session.query(Trade).filter(Trade.id == trade_id).first()
        if trade:
            trade.exit_price = exit_price
            trade.exit_time = datetime.now()
            trade.exit_reason = exit_reason
            trade.pnl_dollar = (exit_price - trade.entry_price) * trade.qty
            trade.pnl_pct = (exit_price - trade.entry_price) / trade.entry_price
            session.commit()
        session.close()

    def get_stats(self):
        session = self.Session()
        wins = session.query(Trade).filter(Trade.pnl_dollar > 0).count()
        losses = session.query(Trade).filter(Trade.pnl_dollar < 0).count()
        total = wins + losses
        
        wr = wins / total if total > 0 else 0
        pnl = session.query(func.sum(Trade.pnl_dollar)).scalar() or 0
        
        session.close()
        return {"win_rate": wr, "total_pnl": pnl, "trades": total}
