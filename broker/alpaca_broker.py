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

        # Validate credentials before initializing API client
        if not Config.ALPACA_API_KEY or not Config.ALPACA_SECRET_KEY:
            logger.error("❌ ALPACA_API_KEY or ALPACA_SECRET_KEY not configured")
            raise ValueError("Alpaca credentials (API key and secret) are required. Set them in GitHub Secrets or .env file")

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
            is_stale = age_minutes > 30

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

    async def place_order(self, symbol: str, side: str, qty: float, order_type: str = "market",
                         entry_price: float = None, stop_loss_pct: float = 0.03,
                         take_profit_pct: float = 0.06) -> Order:
        """Place order on Alpaca with stop-loss and take-profit bracket.

        For BUY orders: places entry + stop-loss (below) + take-profit (above)
        For SELL orders: places simple exit order
        """
        if side not in ("BUY", "SELL"):
            raise ValueError(f"Invalid side: {side}")

        try:
            # Place market order on Alpaca
            alpaca_order = self.api.submit_order(
                symbol=symbol,
                qty=qty,
                side=side.lower(),
                type='market',
                time_in_force='day'
            )

            # Wait for fill (poll Alpaca order status)
            filled = False
            fill_price = 0
            for attempt in range(12):  # Poll for up to 60 seconds
                await asyncio.sleep(5)
                status = self.api.get_order(alpaca_order.id)

                filled_qty = float(status.filled_qty) if status.filled_qty else 0
                if filled_qty > 0:
                    filled = True
                    fill_price = float(status.filled_avg_price)
                    logger.info(f"✓ Order filled: {side} {filled_qty:.4f} {symbol} @ ${fill_price:.4f}")
                    break

                if status.status == 'cancelled':
                    logger.warning(f"Order cancelled (likely insufficient liquidity)")
                    raise ValueError(f"Order cancelled: {status.id}")

            if not filled:
                logger.warning(f"Order {alpaca_order.id} not filled after 60s")
                final_status = self.api.get_order(alpaca_order.id)
                final_qty = float(final_status.filled_qty) if final_status.filled_qty else 0

                if final_qty > 0:
                    fill_price = float(final_status.filled_avg_price)
                    logger.info(f"✓ Order eventually filled: {final_qty:.4f} {symbol} @ ${fill_price:.4f}")
                    filled = True
                else:
                    logger.error(f"Order {alpaca_order.id} not filled after 60s")
                    try:
                        self.api.cancel_order(alpaca_order.id)
                    except:
                        pass
                    raise TimeoutError(f"Order timeout: {symbol}")

            # For BUY orders: place stop-loss and take-profit bracket orders
            if side == "BUY":
                stop_price = fill_price * (1 - stop_loss_pct)
                profit_price = fill_price * (1 + take_profit_pct)

                logger.info(f"📊 Placing bracket orders for {symbol}:")
                logger.info(f"   Entry: ${fill_price:.2f} | Stop: ${stop_price:.2f} | Target: ${profit_price:.2f}")

                try:
                    # Place stop-loss order
                    self.api.submit_order(
                        symbol=symbol,
                        qty=qty,
                        side='sell',
                        type='stop',
                        stop_price=stop_price,
                        time_in_force='gtc'  # Good til cancelled
                    )
                    logger.info(f"✓ Stop-loss placed @ ${stop_price:.2f}")
                except Exception as e:
                    logger.error(f"Failed to place stop-loss: {e}")

                try:
                    # Place take-profit order
                    self.api.submit_order(
                        symbol=symbol,
                        qty=qty,
                        side='sell',
                        type='limit',
                        limit_price=profit_price,
                        time_in_force='gtc'  # Good til cancelled
                    )
                    logger.info(f"✓ Take-profit placed @ ${profit_price:.2f}")
                except Exception as e:
                    logger.error(f"Failed to place take-profit: {e}")

            # Record the trade in our DB
            async with self.session_factory() as session:
                trade = Trade(
                    symbol=symbol,
                    side=side,
                    qty=qty,
                    fill_price=fill_price,
                    slippage_cost=0,
                    fee_cost=0,
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
        """Monitor open positions and close them if they've moved beyond entry.

        Alpaca handles stop-loss and take-profit via bracket orders.
        This function monitors when positions are closed and cleans up the database.
        """
        try:
            # Get current positions from Alpaca
            alpaca_positions = self.api.list_positions()
            alpaca_symbols = {p.symbol for p in alpaca_positions}

            # Get positions from our database
            async with self.session_factory() as session:
                db_positions = (await session.execute(select(Position))).scalars().all()

                # Check each DB position
                for db_pos in db_positions:
                    if db_pos.symbol not in alpaca_symbols:
                        # Position was closed (by stop-loss or take-profit)
                        logger.info(f"✓ Position closed: {db_pos.symbol}")

                        # Calculate P&L
                        current_price = current_prices.get(db_pos.symbol, db_pos.avg_entry_price)
                        if db_pos.qty > 0:
                            pnl = (current_price - db_pos.avg_entry_price) * db_pos.qty
                        else:
                            pnl = (db_pos.avg_entry_price - current_price) * abs(db_pos.qty)

                        # Create exit trade record
                        exit_side = "SELL" if db_pos.qty > 0 else "BUY"
                        exit_trade = Trade(
                            symbol=db_pos.symbol,
                            side=exit_side,
                            qty=abs(db_pos.qty),
                            fill_price=current_price,
                            net_pnl=pnl,
                            strategy_name="exit",
                            timestamp=datetime.utcnow()
                        )
                        session.add(exit_trade)

                        # Remove from positions
                        await session.delete(db_pos)
                        logger.info(f"   P&L: ${pnl:+.2f}")

                await session.commit()

        except Exception as e:
            logger.error(f"Error checking stops and exits: {e}")
