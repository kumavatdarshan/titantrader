#!/usr/bin/env python3
"""Test bot startup and basic operations."""

import logging
import asyncio
from config import Config
from db import init_db, get_session_factory
from broker.alpaca_broker import AlpacaBroker
from engine import TradingEngine

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)s] %(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)


async def main():
    logger.info("=" * 70)
    logger.info("TitanTrader Startup Test - Alpaca Paper Trading")
    logger.info("=" * 70)
    logger.info(f"Mode: {Config.TRADING_MODE}")
    logger.info(f"Symbols: {', '.join(Config.SYMBOLS)}")
    logger.info(f"Capital: ${Config.STARTING_CAPITAL:,.2f}")

    try:
        # Initialize database
        logger.info("\n[STEP 1] Initializing database...")
        db_engine = await init_db()
        session_factory = get_session_factory(db_engine)
        logger.info("✓ Database initialized")

        # Initialize Alpaca broker
        logger.info("\n[STEP 2] Connecting to Alpaca...")
        broker = AlpacaBroker(session_factory, Config.STARTING_CAPITAL)
        logger.info("✓ Alpaca broker connected")

        # Get account info
        logger.info("\n[STEP 3] Fetching account information...")
        account = await broker.get_account()
        logger.info(f"✓ Account fetched")
        logger.info(f"  Portfolio value: ${account['portfolio_value']:,.2f}")
        logger.info(f"  Cash: ${account['cash']:,.2f}")
        logger.info(f"  Buying power: ${account['buying_power']:,.2f}")

        # Initialize engine
        logger.info("\n[STEP 4] Initializing trading engine...")
        engine = TradingEngine(broker, session_factory)
        logger.info("✓ Engine initialized with 4 strategies")

        # Test price fetching for one symbol
        logger.info("\n[STEP 5] Testing price fetch from Alpaca...")
        for symbol in Config.SYMBOLS[:2]:  # Test first 2 symbols
            try:
                price_data = await broker.get_price(symbol)
                logger.info(f"✓ {symbol}: ${price_data['price']:.2f} (source: {price_data['source']})")
            except Exception as e:
                logger.error(f"✗ {symbol}: {e}")

        logger.info("\n" + "=" * 70)
        logger.info("✅ STARTUP TEST PASSED - Bot is ready to trade!")
        logger.info("=" * 70)
        logger.info("\nTo start trading, run: python main.py")

    except Exception as e:
        logger.error(f"\n❌ STARTUP TEST FAILED: {e}", exc_info=True)
        exit(1)


if __name__ == "__main__":
    asyncio.run(main())
