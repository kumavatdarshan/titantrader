import logging
from datetime import datetime
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy import (
    Column, Integer, String, Float, DateTime, Boolean, Text, ForeignKey, BigInteger
)
from config import Config

logger = logging.getLogger(__name__)
Base = declarative_base()


class Price(Base):
    __tablename__ = "prices"
    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)
    symbol = Column(String(20), nullable=False)
    price = Column(Float, nullable=False)
    volume = Column(BigInteger, nullable=True)
    source = Column(String(50), nullable=False)
    is_stale = Column(Boolean, default=False)


class Trade(Base):
    __tablename__ = "trades"
    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)
    symbol = Column(String(20), nullable=False)
    side = Column(String(10), nullable=False)
    qty = Column(Float, nullable=False)
    fill_price = Column(Float, nullable=False)
    slippage_cost = Column(Float, default=0.0)
    fee_cost = Column(Float, default=0.0)
    gross_pnl = Column(Float, default=0.0)
    net_pnl = Column(Float, default=0.0)
    strategy_name = Column(String(50), nullable=False)
    entry_trade_id = Column(Integer, nullable=True)
    hold_duration_seconds = Column(Integer, nullable=True)
    exit_reason = Column(String(50), nullable=True)


class Position(Base):
    __tablename__ = "positions"
    id = Column(Integer, primary_key=True)
    symbol = Column(String(20), nullable=False)
    qty = Column(Float, nullable=False)
    avg_entry_price = Column(Float, nullable=False)
    opened_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    stop_loss_price = Column(Float, nullable=True)
    take_profit_price = Column(Float, nullable=True)
    strategy_name = Column(String(50), nullable=False)
    unrealized_pnl = Column(Float, default=0.0)


class Strategy(Base):
    __tablename__ = "strategies"
    id = Column(Integer, primary_key=True)
    name = Column(String(50), nullable=False, unique=True)
    is_active = Column(Boolean, default=False)
    win_rate = Column(Float, default=0.0)
    avg_net_pnl = Column(Float, default=0.0)
    total_trades = Column(Integer, default=0)
    sharpe_ratio = Column(Float, default=0.0)
    max_drawdown = Column(Float, default=0.0)
    last_backtest_at = Column(DateTime, nullable=True)
    backtest_passed = Column(Boolean, default=False)
    notes = Column(Text, nullable=True)


class EquitySnapshot(Base):
    __tablename__ = "equity_snapshots"
    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)
    total_value = Column(Float, nullable=False)
    cash = Column(Float, nullable=False)
    positions_value = Column(Float, nullable=False)
    peak_value = Column(Float, nullable=False)
    current_drawdown_pct = Column(Float, default=0.0)


class MLRun(Base):
    __tablename__ = "ml_runs"
    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)
    accuracy = Column(Float, nullable=False)
    f1_score = Column(Float, nullable=False)
    n_samples = Column(Integer, nullable=False)
    top_features = Column(Text, nullable=True)
    model_path = Column(String(255), nullable=False)
    was_deployed = Column(Boolean, default=False)


class Lesson(Base):
    __tablename__ = "lessons"
    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)
    trigger = Column(String(100), nullable=False)
    description = Column(Text, nullable=False)
    action_taken = Column(Text, nullable=True)
    strategies_affected = Column(String(255), nullable=True)
    equity_at_time = Column(Float, nullable=False)


async def init_db():
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{Config.DB_PATH}",
        echo=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info(f"Database initialized at {Config.DB_PATH}")
    return engine


def get_session_factory(engine):
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
