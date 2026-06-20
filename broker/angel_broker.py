import logging
import asyncio
from datetime import datetime
from dataclasses import dataclass
from typing import Optional
from sqlalchemy import select
from broker.base import Broker, Order
from db import Position, Trade
from config import Config

logger = logging.getLogger(__name__)


class AngelBroker(Broker):
    """Angel One SmartAPI Broker for NSE Indian market trading."""

    def __init__(self, session_factory, starting_capital: float):
        """Initialize Angel SmartAPI connection."""
        self.session_factory = session_factory
        self.starting_capital = starting_capital
        self.cash = starting_capital
        self.peak_value = starting_capital
        self.last_prices = {}
        self.api = None
        self.token = None

        if Config.is_angel_mode():
            self._init_angel_api()

    def _init_angel_api(self):
        """Initialize SmartConnect API for Angel One."""
        try:
            from SmartApi import SmartConnect
            from pyotp import TOTP

            if not Config.ANGEL_API_KEY or not Config.ANGEL_ACCESS_TOKEN:
                logger.error("Angel API credentials missing (ANGEL_API_KEY, ANGEL_ACCESS_TOKEN)")
                raise ValueError("Angel One credentials not configured")

            self.smartconnect = SmartConnect(api_key=Config.ANGEL_API_KEY)

            # Set access token
            self.smartconnect.set_client_code(Config.ANGEL_CLIENT_ID)
            self.token = Config.ANGEL_ACCESS_TOKEN

            logger.info("✓ Angel One SmartAPI initialized")

        except ImportError:
            logger.error("smartapi-python not installed. Run: pip install smartapi-python pyotp")
            raise
        except Exception as e:
            logger.error(f"Failed to initialize Angel API: {e}")
            raise

    async def get_price(self, symbol: str) -> dict:
        """Fetch current NSE price from Angel SmartAPI."""
        try:
            if not Config.is_angel_mode():
                # Fallback to yfinance for testing
                from data import fetch_price
                return await fetch_price(symbol, use_mock=True)

            # Get live price from Angel SmartAPI
            try:
                response = self.smartconnect.ltpData("NSE", symbol, self.token)
                if response and response.get("status") == "success":
                    data = response.get("data", {})
                    price = float(data.get("ltp", 0))
                    if price > 0:
                        return {
                            "price": price,
                            "timestamp": datetime.utcnow(),
                            "source": "angel",
                            "is_stale": False,
                            "volume": int(data.get("volume", 0))
                        }
            except Exception as api_error:
                if "Invalid Token" in str(api_error):
                    logger.error("ACCESS TOKEN EXPIRED — Update ANGEL_ACCESS_TOKEN in GitHub Secrets")
                    raise
                logger.warning(f"Angel API error for {symbol}: {api_error}")

            # Fallback to yfinance with .NS suffix
            from data import fetch_price
            return await fetch_price(symbol + ".NS", use_mock=True)

        except Exception as e:
            logger.error(f"Failed to fetch price for {symbol}: {e}")
            raise

    async def get_account(self) -> dict:
        """Get account balance and portfolio value."""
        try:
            if Config.is_angel_mode() and Config.TRADING_MODE == "angel_live":
                # Live mode: fetch from API
                try:
                    response = self.smartconnect.rmsLimit()
                    if response and response.get("status") == "success":
                        data = response.get("data", {})
                        cash = float(data.get("net", 0))
                        buying_power = float(data.get("availablecash", cash))
                    else:
                        logger.warning("Failed to get rmsLimit from Angel")
                        cash = self.cash
                        buying_power = self.cash * 4
                except Exception as api_error:
                    if "Invalid Token" in str(api_error):
                        logger.error("ACCESS TOKEN EXPIRED — Update ANGEL_ACCESS_TOKEN in GitHub Secrets")
                        raise
                    logger.warning(f"Angel API error: {api_error}, using cached values")
                    cash = self.cash
                    buying_power = self.cash * 4
            else:
                # Paper mode: compute from DB
                cash = self.cash
                buying_power = self.cash * 4

            # Calculate positions value from DB
            async with self.session_factory() as session:
                positions = await session.execute(select(Position))
                pos_list = positions.scalars().all()

            positions_value = sum(p.qty * self.last_prices.get(p.symbol, p.avg_entry_price) for p in pos_list)
            portfolio_value = cash + positions_value

            # Update peak value
            if portfolio_value > self.peak_value:
                self.peak_value = portfolio_value

            return {
                "cash": cash,
                "portfolio_value": portfolio_value,
                "positions_value": positions_value,
                "peak_value": self.peak_value,
                "buying_power": buying_power
            }

        except Exception as e:
            logger.error(f"Failed to get account info: {e}")
            raise

    async def place_order(
        self,
        symbol: str,
        side: str,
        qty: float,
        order_type: str = "market",
        stop_loss_pct: float = 0.03,
        take_profit_pct: float = 0.06
    ) -> Order:
        """Place buy/sell order."""
        try:
            current_price = self.last_prices.get(symbol, 0)
            if current_price <= 0:
                from data import fetch_price
                price_data = await fetch_price(symbol, use_mock=True)
                current_price = price_data["price"]
                self.last_prices[symbol] = current_price

            fill_price = current_price

            if Config.TRADING_MODE == "angel_live":
                # Live mode: place actual order
                try:
                    order_req = {
                        "variety": "NORMAL",
                        "tradingsymbol": symbol,
                        "symboltoken": self._get_symbol_token(symbol),
                        "transactiontype": "BUY" if side == "BUY" else "SELL",
                        "exchange": "NSE",
                        "ordertype": "MARKET",
                        "quantity": int(qty),
                        "product": "CNC",  # Cash & Carry (delivery)
                        "pricetype": "MARKET"
                    }
                    response = self.smartconnect.placeOrder(order_req)
                    if response and response.get("status") == "success":
                        order_id = response.get("data", {}).get("orderid", f"angel_{symbol}_{int(datetime.utcnow().timestamp())}")
                        fill_price = current_price
                    else:
                        logger.error(f"Order placement failed: {response}")
                        raise Exception(f"Angel order failed: {response}")
                except Exception as api_error:
                    if "Invalid Token" in str(api_error):
                        logger.error("ACCESS TOKEN EXPIRED — Update ANGEL_ACCESS_TOKEN in GitHub Secrets")
                        raise
                    logger.error(f"Angel API order error: {api_error}")
                    raise
            else:
                # Paper mode: simulate order
                order_id = f"paper_{symbol}_{int(datetime.utcnow().timestamp())}"

            # Update cash
            cost = qty * fill_price * (1 + Config.FEE_RATE)
            if side == "BUY":
                self.cash -= cost
                if self.cash < 0:
                    logger.error(f"Insufficient cash for {symbol} BUY: need ${cost:.2f}, have ${self.cash + cost:.2f}")
                    raise ValueError("Insufficient cash")
            else:
                self.cash += cost

            # Record position
            async with self.session_factory() as session:
                if side == "BUY":
                    position = Position(
                        symbol=symbol,
                        qty=qty,
                        avg_entry_price=fill_price,
                        strategy_name="consensus",
                        stop_loss_price=fill_price * (1 - stop_loss_pct),
                        take_profit_price=fill_price * (1 + take_profit_pct)
                    )
                    session.add(position)
                await session.commit()

            logger.info(f"{symbol}: {side} order placed. Qty={qty:.4f}, Price=${fill_price:.2f}, Total=${cost:.2f}")

            return Order(
                order_id=order_id,
                symbol=symbol,
                side=side,
                qty=qty,
                fill_price=fill_price,
                status="FILLED",
                timestamp=datetime.utcnow()
            )

        except Exception as e:
            logger.error(f"Order failed for {symbol}: {e}")
            raise

    async def get_positions(self) -> list:
        """Get current open positions."""
        try:
            async with self.session_factory() as session:
                positions = await session.execute(select(Position))
                pos_list = positions.scalars().all()

            return [
                {
                    "symbol": p.symbol,
                    "qty": p.qty,
                    "avg_price": p.avg_entry_price,
                    "unrealized_pnl": p.unrealized_pnl or 0.0
                }
                for p in pos_list
            ]

        except Exception as e:
            logger.error(f"Failed to get positions: {e}")
            raise

    async def get_order_status(self, order_id: str) -> str:
        """Get order status."""
        try:
            if Config.TRADING_MODE == "angel_live":
                try:
                    response = self.smartconnect.individualOrderDetails(order_id)
                    if response and response.get("status") == "success":
                        return response.get("data", {}).get("orderstatus", "UNKNOWN").upper()
                except Exception as api_error:
                    if "Invalid Token" in str(api_error):
                        logger.error("ACCESS TOKEN EXPIRED — Update ANGEL_ACCESS_TOKEN in GitHub Secrets")
                        raise
                    logger.warning(f"Angel API error: {api_error}")
            return "FILLED"  # Paper mode always filled
        except Exception as e:
            logger.error(f"Failed to get order status: {e}")
            return "UNKNOWN"

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an order."""
        try:
            if Config.TRADING_MODE == "angel_live":
                try:
                    response = self.smartconnect.cancelOrder(order_id, "NORMAL")
                    return response.get("status") == "success"
                except Exception as api_error:
                    if "Invalid Token" in str(api_error):
                        logger.error("ACCESS TOKEN EXPIRED — Update ANGEL_ACCESS_TOKEN in GitHub Secrets")
                        raise
                    logger.warning(f"Failed to cancel order: {api_error}")
            return True
        except Exception as e:
            logger.error(f"Cancel order failed: {e}")
            return False

    async def check_stops_and_exits(self, current_prices: dict):
        """Check stop-loss and take-profit levels, close positions if hit."""
        try:
            closed_positions = []

            async with self.session_factory() as session:
                positions = await session.execute(select(Position))
                pos_list = positions.scalars().all()

                for pos in pos_list:
                    if pos.symbol not in current_prices:
                        continue

                    current_price = current_prices[pos.symbol]
                    self.last_prices[pos.symbol] = current_price

                    # Check stop-loss
                    if pos.stop_loss_price and current_price <= pos.stop_loss_price:
                        logger.info(f"{pos.symbol}: Stop-loss hit (${current_price:.2f} <= ${pos.stop_loss_price:.2f})")
                        await self._close_position(session, pos, current_price, "STOP_LOSS")
                        closed_positions.append(pos)

                    # Check take-profit
                    elif pos.take_profit_price and current_price >= pos.take_profit_price:
                        logger.info(f"{pos.symbol}: Take-profit hit (${current_price:.2f} >= ${pos.take_profit_price:.2f})")
                        await self._close_position(session, pos, current_price, "TAKE_PROFIT")
                        closed_positions.append(pos)

                await session.commit()

            return closed_positions

        except Exception as e:
            logger.error(f"Stop/exit check failed: {e}")
            return []

    async def _close_position(self, session, position, exit_price: float, reason: str):
        """Close a position and record the trade."""
        try:
            pnl = (exit_price - position.avg_entry_price) * position.qty
            net_pnl = pnl * (1 - Config.FEE_RATE)

            trade = Trade(
                symbol=position.symbol,
                side="SELL",
                qty=position.qty,
                fill_price=exit_price,
                gross_pnl=pnl,
                net_pnl=net_pnl,
                strategy_name=position.strategy_name,
                entry_trade_id=position.id,
                exit_reason=reason
            )
            session.add(trade)
            self.cash += (pnl * (1 - Config.FEE_RATE))
            session.delete(position)

            logger.info(f"{position.symbol}: Closed via {reason} | Net P&L: ${net_pnl:.2f}")

        except Exception as e:
            logger.error(f"Failed to close position: {e}")

    def _get_symbol_token(self, symbol: str) -> str:
        """Get Angel symbol token for NSE symbol (hardcoded mapping)."""
        # Simplified mapping for common NSE stocks
        tokens = {
            "RELIANCE": "4742401",
            "INFY": "1594550",
            "TCS": "3341761",
            "HDFCBANK": "1995679",
            "ICICIBANK": "208652545",
            "WIPRO": "3352577",
            "SBIN": "4119817",
            "KOTAKBANK": "2285089",
            "AXISBANK": "2030593",
        }
        return tokens.get(symbol, "0")
