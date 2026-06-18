#!/usr/bin/env python3
"""Test one complete trading cycle with strategies."""

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
    logger.info("TitanTrader Full Cycle Test - Alpaca Paper Trading")
    logger.info("=" * 70)

    try:
        # Initialize
        logger.info("\n[1] Initializing database and broker...")
        db_engine = await init_db()
        session_factory = get_session_factory(db_engine)
        broker = AlpacaBroker(session_factory, Config.STARTING_CAPITAL)

        # Initialize engine
        logger.info("\n[2] Initializing trading engine...")
        engine = TradingEngine(broker, session_factory)

        # Run ONE full trading cycle
        logger.info("\n[3] Running ONE full trading cycle...")
        logger.info("     (This fetches real Alpaca data and generates signals)")
        logger.info("-" * 70)

        await engine.run_cycle()

        logger.info("-" * 70)
        logger.info("\n[4] Checking results...")

        # Check account state after cycle
        account = await broker.get_account()
        logger.info(f"\n✓ Account updated:")
        logger.info(f"  Portfolio value: ${account['portfolio_value']:,.2f}")
        logger.info(f"  Cash: ${account['cash']:,.2f}")
        logger.info(f"  Positions value: ${account['positions_value']:,.2f}")

        # Check if any positions were opened
        positions = await broker.get_positions()
        if positions:
            logger.info(f"\n✓ Opened {len(positions)} position(s):")
            for pos in positions:
                logger.info(f"  {pos['symbol']}: {pos['qty']} shares @ ${pos['avg_price']:.2f}")
        else:
            logger.info("\n✓ No positions opened (normal if no strong signals)")

        # Check equity snapshot
        async with session_factory() as session:
            from db import EquitySnapshot
            from sqlalchemy import select
            result = await session.execute(
                select(EquitySnapshot).order_by(EquitySnapshot.id.desc()).limit(1)
            )
            latest_snapshot = result.scalar_one_or_none()
            if latest_snapshot:
                logger.info(f"\n✓ Equity snapshot saved:")
                logger.info(f"  Time: {latest_snapshot.timestamp}")
                logger.info(f"  Total value: ${latest_snapshot.total_value:,.2f}")
                logger.info(f"  Drawdown: {latest_snapshot.current_drawdown_pct:.2f}%")

        logger.info("\n" + "=" * 70)
        logger.info("✅ FULL CYCLE TEST PASSED!")
        logger.info("=" * 70)
        logger.info("\nThe bot is ready for continuous trading.")
        logger.info("It will run this cycle every 5 minutes when you start main.py")

    except Exception as e:
        logger.error(f"\n❌ TEST FAILED: {e}", exc_info=True)
        exit(1)


if __name__ == "__main__":
    asyncio.run(main())
