#!/usr/bin/env python3
"""Run a single trading cycle for GitHub Actions."""
import asyncio
import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)s] %(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)

async def main():
    try:
        from config import Config
        from db import init_db, get_session_factory
        from broker.paper_broker import PaperBroker
        from broker.alpaca_broker import AlpacaBroker
        from engine import TradingEngine
        from learner import Learner

        logger.info("=" * 60)
        logger.info("TitanTrader Single Cycle")
        logger.info("=" * 60)
        logger.info(f"Mode: {Config.TRADING_MODE}")
        logger.info(f"Symbols: {', '.join(Config.SYMBOLS)}")

        db_engine = await init_db()
        session_factory = get_session_factory(db_engine)

        if Config.TRADING_MODE == "local_paper":
            broker = PaperBroker(session_factory, Config.STARTING_CAPITAL)
            logger.info("Using local paper broker (yfinance + SQLite)")
        else:
            broker = AlpacaBroker(session_factory, Config.STARTING_CAPITAL)
            logger.info(f"Using Alpaca broker ({Config.TRADING_MODE})")
        engine = TradingEngine(broker, session_factory)
        learner = Learner(session_factory)

        logger.info("Running trading cycle...")
        await engine.run_cycle()

        logger.info("Checking if ML retraining needed...")
        from sqlalchemy import select
        from db import Trade
        async with session_factory() as session:
            result = await session.execute(select(Trade))
            trades = result.scalars().all()
            if len(trades) >= Config.ML_MIN_TRADES_TO_TRAIN:
                logger.info(f"Retraining ML on {len(trades)} trades...")
                await learner.retrain_ml_model()
            else:
                logger.info(f"Not enough trades yet ({len(trades)}/{Config.ML_MIN_TRADES_TO_TRAIN})")

        logger.info("=" * 60)
        logger.info("Cycle complete")
        logger.info("=" * 60)
        return 0

    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        return 1

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
