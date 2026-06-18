import logging
import asyncio
from datetime import datetime
from sqlalchemy import select
from broker.base import Broker
from strategies import EMACrossStrategy, RSIReversionStrategy, MACDMomentumStrategy, MLPredictorStrategy
from db import Position, Trade, Strategy as StrategyModel, EquitySnapshot, Lesson
from config import Config
from risk import PositionSizer
from data import fetch_price, fetch_ohlcv_candles
import pandas as pd

logger = logging.getLogger(__name__)


class TradingEngine:
    def __init__(self, broker: Broker, session_factory):
        self.broker = broker
        self.session_factory = session_factory
        self.strategies = [
            EMACrossStrategy(),
            RSIReversionStrategy(),
            MACDMomentumStrategy(),
            MLPredictorStrategy()
        ]
        self.is_paused = False
        self.pause_reason = None

    async def run_cycle(self):
        """Run one full trading cycle."""
        try:
            logger.info("=" * 60)
            logger.info("TRADING CYCLE START")
            logger.info("=" * 60)

            await self._check_drawdown_guard()
            if self.is_paused:
                logger.warning(f"TRADING PAUSED: {self.pause_reason}")
                return

            current_prices = await self._fetch_all_prices()
            await self.broker.check_stops_and_exits(current_prices)

            await self._generate_and_execute_signals(current_prices)
            await self._save_equity_snapshot()

            logger.info("=" * 60)
            logger.info("TRADING CYCLE END")
            logger.info("=" * 60)

        except Exception as e:
            logger.error(f"Trading cycle error: {e}", exc_info=True)

    async def _check_drawdown_guard(self):
        """Check if drawdown exceeds limit."""
        account = await self.broker.get_account()
        drawdown = (account['peak_value'] - account['portfolio_value']) / account['peak_value']

        if drawdown >= Config.DRAWDOWN_PAUSE_PCT:
            logger.error(f"DRAWDOWN LIMIT HIT: {drawdown*100:.2f}% >= {Config.DRAWDOWN_PAUSE_PCT*100:.2f}%")
            self.is_paused = True
            self.pause_reason = f"Drawdown {drawdown*100:.2f}% exceeds limit"

            await self._close_all_positions()

            async with self.session_factory() as session:
                lesson = Lesson(
                    trigger="DRAWDOWN_EXCEEDED",
                    description=f"Drawdown reached {drawdown*100:.2f}%. All positions closed.",
                    strategies_affected="all",
                    equity_at_time=account['portfolio_value']
                )
                session.add(lesson)
                await session.commit()

    async def _fetch_all_prices(self) -> dict:
        """Fetch current prices for all symbols."""
        prices = {}
        for symbol in Config.SYMBOLS:
            try:
                if Config.TRADING_MODE.startswith("alpaca"):
                    # Use broker's price fetching for Alpaca (real Alpaca prices)
                    price_data = await self.broker.get_price(symbol)
                else:
                    # Use yfinance for local paper trading
                    use_mock = Config.is_paper_mode()
                    price_data = await fetch_price(symbol, use_mock=use_mock)

                if not price_data['is_stale']:
                    prices[symbol] = price_data['price']
                else:
                    logger.warning(f"{symbol}: Stale price (>10min old), skipping")
            except Exception as e:
                logger.error(f"Failed to fetch {symbol}: {e}")

        return prices

    async def _generate_and_execute_signals(self, current_prices: dict):
        """Generate signals from all strategies and execute trades."""
        async with self.session_factory() as session:
            for symbol in Config.SYMBOLS:
                if symbol not in current_prices:
                    continue

                current_price = current_prices[symbol]

                candle_result = await fetch_ohlcv_candles(symbol, period="1mo")
                if not candle_result['success'] or candle_result['data'] is None:
                    logger.warning(f"{symbol}: Cannot fetch real OHLCV, skipping signals")
                    continue

                df = candle_result['data']

                signals = []
                for strategy in self.strategies:
                    try:
                        signal = await strategy.generate_signal(symbol, df)
                        signals.append((strategy.name, signal))
                        logger.info(f"{symbol} [{strategy.name}]: {signal.direction} ({signal.confidence*100:.1f}%)")

                    except Exception as e:
                        logger.error(f"{symbol} [{strategy.name}]: {e}", exc_info=True)

                await self._execute_consensus_trade(session, symbol, current_price, signals)

    async def _execute_consensus_trade(self, session, symbol, price, signals):
        """Execute trade if 2+ strategies agree."""
        buy_signals = sum(1 for _, s in signals if s.direction == "BUY")
        sell_signals = sum(1 for _, s in signals if s.direction == "SELL")

        if buy_signals >= 2:
            logger.info(f"{symbol}: BUY consensus ({buy_signals}/{len(signals)} strategies)")
            await self._place_buy_order(session, symbol, price)

        elif sell_signals >= 2:
            logger.info(f"{symbol}: SELL consensus ({sell_signals}/{len(signals)} strategies)")
            await self._place_sell_order(session, symbol, price)

    async def _place_buy_order(self, session, symbol, price):
        """Place a buy order if conditions met."""
        try:
            account = await self.broker.get_account()
            positions = await session.execute(select(Position))
            pos_list = positions.scalars().all()

            qty = PositionSizer.calculate_position_size(
                portfolio_value=account['portfolio_value'],
                cash=account['cash'],
                symbol=symbol,
                win_rate=0.52,
                avg_win=100,
                avg_loss=100,
                current_price=price,
                existing_positions={p.symbol: p for p in pos_list}
            )

            if qty <= 0:
                logger.warning(f"{symbol}: Cannot size position (qty={qty:.4f})")
                return

            order = await self.broker.place_order(symbol, "BUY", qty)

            new_pos = Position(
                symbol=symbol,
                qty=qty,
                avg_entry_price=order.fill_price,
                strategy_name="consensus",
                stop_loss_price=order.fill_price * (1 - Config.STOP_LOSS_PCT),
                take_profit_price=order.fill_price * (1 + Config.TAKE_PROFIT_PCT)
            )
            session.add(new_pos)
            await session.commit()

            logger.info(f"{symbol}: BUY order filled. Qty={qty:.4f}, Price=${order.fill_price:.2f}")

        except Exception as e:
            logger.error(f"{symbol}: Buy order failed: {e}")

    async def _place_sell_order(self, session, symbol, price):
        """Close existing position or short (if supported)."""
        try:
            pos_result = await session.execute(select(Position).where(Position.symbol == symbol))
            position = pos_result.scalar_one_or_none()

            if position:
                await self.broker.place_order(symbol, "SELL", position.qty)
                await session.delete(position)
                await session.flush()
                await session.commit()
                logger.info(f"{symbol}: Position closed. P&L: ${position.unrealized_pnl:.2f}")

        except Exception as e:
            logger.error(f"{symbol}: Sell order failed: {e}")

    async def _close_all_positions(self):
        """Emergency close all positions."""
        try:
            current_prices = await self._fetch_all_prices()

            async with self.session_factory() as session:
                positions = await session.execute(select(Position))
                pos_list = positions.scalars().all()

                for pos in pos_list:
                    if pos.symbol in current_prices:
                        price = current_prices[pos.symbol]
                        await self.broker.place_order(pos.symbol, "SELL", pos.qty)
                        await session.delete(pos)

                await session.flush()
                await session.commit()
                logger.info(f"Emergency close: {len(pos_list)} positions closed")

        except Exception as e:
            logger.error(f"Emergency close failed: {e}")

    async def _save_equity_snapshot(self):
        """Save current portfolio state."""
        try:
            account = await self.broker.get_account()
            drawdown = (account['peak_value'] - account['portfolio_value']) / account['peak_value']

            snapshot = EquitySnapshot(
                total_value=account['portfolio_value'],
                cash=account['cash'],
                positions_value=account['positions_value'],
                peak_value=account['peak_value'],
                current_drawdown_pct=drawdown
            )

            async with self.session_factory() as session:
                session.add(snapshot)
                await session.commit()

                logger.info(
                    f"Equity: ${account['portfolio_value']:.2f} | "
                    f"Cash: ${account['cash']:.2f} | "
                    f"Drawdown: {drawdown*100:.2f}%"
                )

        except Exception as e:
            logger.error(f"Equity snapshot failed: {e}")
