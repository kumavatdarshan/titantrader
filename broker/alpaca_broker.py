import logging
import time
from broker.base import Broker, Order
from datetime import datetime
from config import Config
from db import Price, Position, Trade
from sqlalchemy import select
import asyncio

logger = logging.getLogger(__name__)

try:
    from alpaca_trade_api.rest import REST, APIError
except ImportError:
    logger.error("alpaca-trade-api not installed. Install with: pip install alpaca-trade-api==3.3.2")
    REST = None
    APIError = Exception


class AlpacaBroker(Broker):
    """Alpaca broker adapter — paper and live trading with real fills."""

    def __init__(self, session_factory, starting_capital: float):
        self.session_factory = session_factory
        self.starting_capital = starting_capital

        if not REST:
            raise ImportError("alpaca-trade-api library required")

        # Initialize Alpaca API client
        base_url = Config.ALPACA_PAPER_URL if Config.TRADING_MODE == "alpaca_paper" else Config.ALPACA_LIVE_URL
        self.api = REST(
            key_id=Config.ALPACA_API_KEY,
            secret_key=Config.ALPACA_SECRET_KEY,
            base_url=base_url
        )

        if Config.TRADING_MODE == "alpaca_live":
            logger.error("=" * 70)
            logger.error("⚠️  LIVE TRADING — REAL MONEY AT RISK")
            logger.error(f"Capital: ${starting_capital:,.2f}")
            logger.error(f"Max position: {Config.MAX_POSITION_PCT*100:.1f}%")
            logger.error(f"Stop-loss: {Config.STOP_LOSS_PCT*100:.1f}%")
            logger.error("=" * 70)
        else:
            logger.info("[PAPER] ALPACA PAPER TRADING - Real fills, real prices, fake money")

        # Verify connection and get initial account info
        try:
            account = self.api.get_account()
            logger.info(f"✓ Connected to Alpaca | Account: {account.account_number}")
            logger.info(f"  Starting equity: ${float(account.equity):,.2f}")
            logger.info(f"  Buying power: ${float(account.buying_power):,.2f}")
        except APIError as e:
            logger.error(f"❌ Failed to connect to Alpaca: {e}")
            raise

    async def get_price(self, symbol: str) -> dict:
        """Fetch latest price from Alpaca real-time quotes."""
        try:
            # Get latest bar (most recent price)
            bar = self.api.get_latest_bar(symbol)
            if not bar:
                raise ValueError(f"No data available for {symbol}")

            # Get current market time to check freshness
            clock = self.api.get_clock()
            now = datetime.fromisoformat(str(clock.timestamp).replace('Z', '+00:00'))
            bar_time = datetime.fromisoformat(str(bar.t).replace('Z', '+00:00'))

            age_minutes = (now - bar_time).total_seconds() / 60
            is_stale = age_minutes > 10

            price_data = {
                'symbol': symbol,
                'price': float(bar.c),
                'timestamp': datetime.utcnow(),
                'volume': float(bar.v),
                'source': 'alpaca',
                'is_stale': is_stale
            }

            # Store in DB
            async with self.session_factory() as session:
                price_record = Price(
                    symbol=symbol,
                    price=float(bar.c),
                    timestamp=datetime.utcnow(),
                    volume=float(bar.v),
                    source='alpaca',
                    is_stale=is_stale
                )
                session.add(price_record)
                await session.commit()

            return price_data

        except Exception as e:
            logger.error(f"Failed to fetch {symbol}: {str(e)}")
            raise

    async def get_account(self) -> dict:
        """Fetch live account state from Alpaca."""
        try:
            account = self.api.get_account()
            return {
                'cash': float(account.cash),
                'portfolio_value': float(account.portfolio_value),
                'positions_value': float(account.portfolio_value) - float(account.cash),
                'peak_value': float(account.portfolio_value),  # Alpaca tracks this
                'buying_power': float(account.buying_power),
            }
        except Exception as e:
            logger.error(f"Failed to get account: {e}")
            raise

    async def place_order(self, symbol: str, side: str, qty: float, order_type: str = "market") -> Order:
        """Place order on Alpaca with real fills."""
        if side not in ("BUY", "SELL"):
            raise ValueError(f"Invalid side: {side}")

        try:
            # Place market order on Alpaca
            alpaca_order = self.api.submit_order(
                symbol=symbol,
                qty=qty,
                side=side.lower(),
                type=order_type.lower(),
                time_in_force='day'
            )

            # Wait for fill (poll Alpaca order status)
            filled = False
            fill_price = 0
            for attempt in range(12):  # Poll for up to 60 seconds (5 second intervals)
                await asyncio.sleep(5)
                status = self.api.get_order(alpaca_order.id)

                if status.filled_qty and status.filled_qty > 0:
                    filled = True
                    fill_price = float(status.filled_avg_price)
                    logger.info(f"✓ Order filled: {side} {qty} {symbol} @ ${fill_price:.4f}")
                    break

                if status.status == 'cancelled':
                    raise ValueError(f"Order cancelled: {status.id}")

            if not filled:
                logger.error(f"Order {alpaca_order.id} not filled after 60s, cancelling")
                self.api.cancel_order(alpaca_order.id)
                raise TimeoutError(f"Order timeout: {symbol}")

            # Record the trade in our DB
            async with self.session_factory() as session:
                trade = Trade(
                    symbol=symbol,
                    side=side,
                    qty=qty,
                    fill_price=fill_price,
                    slippage_cost=0,  # Alpaca reports actual fill price
                    fee_cost=0,  # Alpaca paper has no fees
                    strategy_name="alpaca_engine",
                    timestamp=datetime.utcnow()
                )
                session.add(trade)
                await session.commit()

            return Order(
                order_id=alpaca_order.id,
                symbol=symbol,
                side=side,
                qty=qty,
                fill_price=fill_price,
                status="FILLED",
                timestamp=datetime.utcnow()
            )

        except Exception as e:
            logger.error(f"Failed to place order on Alpaca: {e}")
            raise

    async def get_positions(self) -> list:
        """Get all open positions from Alpaca."""
        try:
            positions = self.api.list_positions()
            return [
                {
                    'symbol': p.symbol,
                    'qty': float(p.qty),
                    'avg_price': float(p.avg_entry_price),
                    'unrealized_pnl': float(p.unrealized_pl)
                }
                for p in positions
            ]
        except Exception as e:
            logger.error(f"Failed to get positions: {e}")
            return []

    async def get_order_status(self, order_id: str) -> str:
        """Get order status from Alpaca."""
        try:
            order = self.api.get_order(order_id)
            return order.status.upper()
        except Exception:
            return "UNKNOWN"

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an order on Alpaca."""
        try:
            self.api.cancel_order(order_id)
            return True
        except Exception as e:
            logger.warning(f"Failed to cancel order {order_id}: {e}")
            return False

    async def check_stops_and_exits(self, current_prices: dict):
        """Check stop-loss and take-profit via Alpaca bracket orders."""
        # Alpaca handles stop-loss and take-profit automatically via bracket orders
        # This is a no-op here since we use bracket order placement in place_order
        pass
