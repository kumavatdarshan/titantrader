#!/usr/bin/env python3
"""Test Alpaca API connection and keys."""

import logging
from config import Config

logging.basicConfig(level=logging.INFO, format='%(asctime)s: %(message)s')
logger = logging.getLogger(__name__)

try:
    from alpaca_trade_api.rest import REST, APIError

    logger.info("=" * 70)
    logger.info("Testing Alpaca API Connection")
    logger.info("=" * 70)

    # Initialize Alpaca API
    base_url = Config.ALPACA_PAPER_URL
    logger.info(f"Base URL: {base_url}")
    logger.info(f"API Key: {Config.ALPACA_API_KEY[:10]}..." if Config.ALPACA_API_KEY else "API Key: NOT SET")

    api = REST(
        key_id=Config.ALPACA_API_KEY,
        secret_key=Config.ALPACA_SECRET_KEY,
        base_url=base_url
    )

    # Test 1: Get account
    logger.info("\n[TEST 1] Getting account information...")
    account = api.get_account()
    logger.info(f"✓ Account: {account.account_number}")
    logger.info(f"  Portfolio value: ${float(account.portfolio_value):,.2f}")
    logger.info(f"  Cash: ${float(account.cash):,.2f}")
    logger.info(f"  Buying power: ${float(account.buying_power):,.2f}")
    logger.info(f"  Equity: ${float(account.equity):,.2f}")

    # Test 2: Get clock (market status)
    logger.info("\n[TEST 2] Getting market clock...")
    clock = api.get_clock()
    logger.info(f"✓ Current time: {clock.timestamp}")
    logger.info(f"  Market is {'OPEN' if clock.is_open else 'CLOSED'}")

    # Test 3: Get latest price for a symbol
    logger.info("\n[TEST 3] Getting latest price for AAPL...")
    bar = api.get_latest_bar("AAPL")
    if bar:
        logger.info(f"✓ AAPL: ${float(bar.c):.2f}")
        logger.info(f"  Volume: {float(bar.v):,.0f}")
        logger.info(f"  Timestamp: {bar.t}")
    else:
        logger.warning("No bar data for AAPL")

    # Test 4: List positions
    logger.info("\n[TEST 4] Getting open positions...")
    positions = api.list_positions()
    if positions:
        logger.info(f"✓ Found {len(positions)} open position(s)")
        for p in positions:
            logger.info(f"  {p.symbol}: {float(p.qty)} shares @ ${float(p.avg_entry_price):.2f}")
    else:
        logger.info("✓ No open positions")

    logger.info("\n" + "=" * 70)
    logger.info("✅ ALL TESTS PASSED - ALPACA CONNECTION IS WORKING")
    logger.info("=" * 70)

except APIError as e:
    logger.error(f"❌ Alpaca API Error: {e}")
    logger.error("  This typically means:")
    logger.error("  - Invalid API keys")
    logger.error("  - Wrong account type (need paper or live matching the URL)")
    logger.error("  - Account not verified")
    exit(1)
except ImportError:
    logger.error("❌ alpaca-trade-api not installed")
    logger.error("  Run: pip install alpaca-trade-api==3.3.2")
    exit(1)
except Exception as e:
    logger.error(f"❌ Unexpected error: {e}")
    exit(1)
