#!/usr/bin/env python3
import logging
import asyncio
import signal
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from config import Config
from db import init_db, get_session_factory, Strategy as StrategyModel
from broker.paper_broker import PaperBroker
from broker.alpaca_broker import AlpacaBroker
from broker.angel_broker import AngelBroker
from engine import TradingEngine
from backtester import Backtester
from learner import Learner
from dashboard.server import create_dashboard
import uvicorn
from threading import Thread
import sys

import io

logging.basicConfig(
    level=Config.LOG_LEVEL,
    format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
    handlers=[
        logging.FileHandler('logs/titantrader.log', encoding='utf-8'),
        logging.StreamHandler(io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8'))
    ]
)
logger = logging.getLogger(__name__)


class TitanTrader:
    def __init__(self):
        self.engine = None
        self.scheduler = None
        self.session_factory = None
        self.broker = None
        self.backtester = None
        self.learner = None

    async def startup(self):
        """Initialize all components."""
        logger.info("=" * 70)
        logger.info("TitanTrader — AI Paper Trading Bot")
        logger.info("=" * 70)
        logger.info(f"Mode: {Config.TRADING_MODE}")
        logger.info(f"Capital: ${Config.STARTING_CAPITAL:,.2f}")
        logger.info(f"Symbols: {', '.join(Config.SYMBOLS)}")
        logger.info(f"Dashboard: http://localhost:{Config.DASHBOARD_PORT}")
        logger.info("=" * 70)
        logger.info("Real prices. Fake money. Zero real risk.")
        logger.info("=" * 70)

        db_engine = await init_db()
        self.session_factory = get_session_factory(db_engine)

        if Config.TRADING_MODE == "local_paper":
            self.broker = PaperBroker(self.session_factory, Config.STARTING_CAPITAL)
            logger.info("Using local paper broker (yfinance + SQLite)")
        elif Config.TRADING_MODE.startswith("alpaca"):
            self.broker = AlpacaBroker(self.session_factory, Config.STARTING_CAPITAL)
            logger.info(f"Using Alpaca broker ({Config.TRADING_MODE})")
        elif Config.TRADING_MODE.startswith("angel"):
            self.broker = AngelBroker(self.session_factory, Config.STARTING_CAPITAL)
            logger.info(f"Using Angel One broker ({Config.TRADING_MODE}) — NSE Indian Market")

        self.engine = TradingEngine(self.broker, self.session_factory)
        self.backtester = Backtester(self.session_factory)
        self.learner = Learner(self.session_factory)

        await self._init_strategies()

        logger.info("Skipping initial backtest (will use live trading data)")
        # Backtest will run automatically every Sunday
        # logger.info("Running initial backtest...")
        # await self.backtester.run_full_backtest()

        self._start_dashboard()
        self._start_scheduler()

        logger.info("TitanTrader started successfully!")

    async def _init_strategies(self):
        """Create strategy records in DB."""
        async with self.session_factory() as session:
            for strategy_name in ["ema_cross", "rsi_reversion", "macd_momentum", "volatility_breakout", "ml_predictor"]:
                result = await session.execute(
                    select(StrategyModel).where(StrategyModel.name == strategy_name)
                )
                if not result.scalar_one_or_none():
                    strat = StrategyModel(name=strategy_name, is_active=True)
                    session.add(strat)
            await session.commit()

    def _start_dashboard(self):
        """Start FastAPI dashboard in background thread."""
        app = create_dashboard(self.session_factory, self.broker, self.engine)
        config = uvicorn.Config(app, host="0.0.0.0", port=Config.DASHBOARD_PORT, log_level="critical")
        server = uvicorn.Server(config)

        def run_server():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(server.serve())

        thread = Thread(target=run_server, daemon=True)
        thread.start()
        logger.info(f"Dashboard started at http://localhost:{Config.DASHBOARD_PORT}")

    def _start_scheduler(self):
        """Start APScheduler for recurring tasks."""
        self.scheduler = AsyncIOScheduler()

        self.scheduler.add_job(
            self.engine.run_cycle,
            trigger=CronTrigger(minute=f"*/{Config.TRADE_INTERVAL_MINUTES}"),
            id='trading_cycle'
        )

        self.scheduler.add_job(
            self.engine._save_equity_snapshot,
            trigger=CronTrigger(minute=0),
            id='equity_snapshot'
        )

        self.scheduler.add_job(
            self.learner.retrain_ml_model,
            trigger=CronTrigger(hour='*/4', minute=0),
            id='ml_retrain'
        )
        logger.info("ML model retrains every 4 hours")

        self.scheduler.add_job(
            self.backtester.run_full_backtest,
            trigger=CronTrigger(day_of_week="6", hour=0, minute=0),
            id='weekly_backtest'
        )

        self.scheduler.add_job(
            self.learner.write_weekly_lesson,
            trigger=CronTrigger(day_of_week="0", hour=6, minute=0),
            id='weekly_lesson'
        )

        self.scheduler.start()
        logger.info("Scheduler started with all jobs")

    async def shutdown(self):
        """Graceful shutdown."""
        logger.info("Shutting down TitanTrader...")

        if self.scheduler:
            self.scheduler.shutdown()

        async with self.session_factory() as session:
            await self.engine._close_all_positions()

            from db import Lesson
            lesson = Lesson(
                trigger="BOT_STOP",
                description="Bot stopped by user",
                strategies_affected="all",
                equity_at_time=0.0
            )
            session.add(lesson)
            await session.commit()

        logger.info("TitanTrader shut down cleanly")
        sys.exit(0)


async def main():
    bot = TitanTrader()

    def signal_handler(sig, frame):
        asyncio.create_task(bot.shutdown())

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    await bot.startup()

    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        await bot.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
