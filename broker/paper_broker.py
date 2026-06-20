import logging
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from broker.base import Broker, Order
from db import Price, Position, Trade
from config import Config
from data import fetch_price

logger = logging.getLogger(__name__)


class DataUnavailableError(Exception):
    pass


class PaperBroker(Broker):
    def __init__(self, session_factory, starting_capital: float):
        self.session_factory = session_factory
        self.cash = starting_capital
        self.starting_capital = starting_capital
        self.peak_value = starting_capital
        self.last_prices = {}

    async def get_price(self, symbol: str) -> dict:
        """Fetch latest price via data layer (yfinance or mock)."""
        try:
            from config import Config
            use_mock = Config.is_paper_mode()
            price_data = await fetch_price(symbol, use_mock=use_mock)

            async with self.session_factory() as session:
                price_record = Price(
                    symbol=symbol,
                    price=price_data['price'],
                    timestamp=price_data['timestamp'],
                    volume=price_data.get('volume', 0),
                    source=price_data['source'],
                    is_stale=price_data['is_stale']
                )
                session.add(price_record)
                await session.commit()

            self.last_prices[symbol] = price_data
            return price_data

        except Exception as e:
            logger.error(f"Failed to fetch {symbol}: {str(e)}")
            raise DataUnavailableError(f"Cannot fetch {symbol}: {str(e)}")

    async def get_account(self) -> dict:
        """Returns account state with current positions valued at market."""
        positions_value = await self._get_positions_value()
        total_value = self.cash + positions_value

        if total_value > self.peak_value:
            self.peak_value = total_value

        return {
            'cash': self.cash,
            'portfolio_value': total_value,
            'positions_value': positions_value,
            'peak_value': self.peak_value,
            'buying_power': self.cash * 4,
        }

    async def place_order(self, symbol: str, side: str, qty: float, order_type: str = "market") -> Order:
        """Place order with realistic fills: slippage + fees applied."""
        if side not in ("BUY", "SELL"):
            raise ValueError(f"Invalid side: {side}")

        price_data = await self.get_price(symbol)
        price = price_data['price']

        if price_data['is_stale']:
            raise DataUnavailableError(f"Cannot trade {symbol} — stale price (>{10}min old)")

        slippage_multiplier = 1 + (Config.SLIPPAGE_BPS / 10000)
        if side == "BUY":
            fill_price = price * slippage_multiplier
            slippage_cost = (fill_price - price) * qty
        else:
            fill_price = price / slippage_multiplier
            slippage_cost = (price - fill_price) * qty

        trade_value = abs(qty * fill_price)
        fee_cost = trade_value * Config.FEE_RATE

        if side == "BUY":
            if self.cash < trade_value + fee_cost:
                raise ValueError(f"Insufficient cash. Need: ${trade_value + fee_cost:.2f}, Have: ${self.cash:.2f}")
            self.cash -= (trade_value + fee_cost)
        else:
            self.cash += (trade_value - fee_cost)

        order = Order(
            order_id=f"paper_{symbol}_{datetime.utcnow().timestamp()}",
            symbol=symbol,
            side=side,
            qty=qty,
            fill_price=fill_price,
            status="FILLED",
            timestamp=datetime.utcnow()
        )

        async with self.session_factory() as session:
            trade = Trade(
                symbol=symbol,
                side=side,
                qty=qty,
                fill_price=fill_price,
                slippage_cost=slippage_cost,
                fee_cost=fee_cost,
                strategy_name="engine",
                timestamp=datetime.utcnow()
            )
            session.add(trade)
            await session.commit()

        logger.info(
            f"Order filled: {side} {qty} {symbol} @ ${fill_price:.4f} "
            f"| Slippage: ${slippage_cost:.4f} | Fee: ${fee_cost:.4f}"
        )

        return order

    async def get_positions(self) -> list:
        """Returns all open positions."""
        async with self.session_factory() as session:
            result = await session.execute(select(Position))
            positions = result.scalars().all()
            return [
                {
                    'symbol': p.symbol,
                    'qty': p.qty,
                    'avg_price': p.avg_entry_price,
                    'unrealized_pnl': p.unrealized_pnl
                }
                for p in positions
            ]

    async def get_order_status(self, order_id: str) -> str:
        return "FILLED"

    async def cancel_order(self, order_id: str) -> bool:
        return True

    async def _get_positions_value(self) -> float:
        """Sum all positions at current market price."""
        async with self.session_factory() as session:
            result = await session.execute(select(Position))
            positions = result.scalars().all()
            total = 0.0

            for pos in positions:
                try:
                    price_data = await self.get_price(pos.symbol)
                    total += pos.qty * price_data['price']
                except Exception as e:
                    logger.warning(f"Could not value {pos.symbol} position: {e}")

            return total

    async def check_stops_and_exits(self, current_prices: dict):
        """Called by engine each cycle to check stop-loss and take-profit levels."""
        async with self.session_factory() as session:
            result = await session.execute(select(Position))
            positions = result.scalars().all()

            for pos in positions:
                if pos.symbol not in current_prices:
                    continue

                current_price = current_prices[pos.symbol]
                unrealized_pnl_pct = (current_price - pos.avg_entry_price) / pos.avg_entry_price

                if pos.stop_loss_price and current_price <= pos.stop_loss_price:
                    logger.warning(f"{pos.symbol}: Stop-loss triggered at ${current_price:.4f}")
                    await self._close_position(session, pos, current_price, "stop_loss")
                    continue

                if pos.take_profit_price and current_price >= pos.take_profit_price:
                    logger.info(f"{pos.symbol}: Take-profit triggered at ${current_price:.4f}")
                    await self._close_position(session, pos, current_price, "take_profit")
                    continue

                pos.unrealized_pnl = pos.qty * (current_price - pos.avg_entry_price)

            await session.commit()

    async def _close_position(self, session, pos, current_price, reason):
        """Close a position and record the trade."""
        gross_pnl = pos.qty * (current_price - pos.avg_entry_price)
        trade_value = abs(pos.qty * current_price)
        fee_cost = trade_value * Config.FEE_RATE
        net_pnl = gross_pnl - fee_cost

        trade = Trade(
            symbol=pos.symbol,
            side="SELL",
            qty=pos.qty,
            fill_price=current_price,
            gross_pnl=gross_pnl,
            net_pnl=net_pnl,
            fee_cost=fee_cost,
            strategy_name=pos.strategy_name,
            exit_reason=reason,
            entry_trade_id=None,
            timestamp=datetime.utcnow()
        )
        session.add(trade)
        self.cash += (trade_value - fee_cost)

        session.delete(pos)
        await session.flush()
        await session.commit()

        logger.info(
            f"{pos.symbol}: Closed via {reason} | Net P&L: ${net_pnl:.2f} ({net_pnl/abs(pos.qty * pos.avg_entry_price)*100:.2f}%)"
        )
