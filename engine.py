import logging
import asyncio
from datetime import datetime
from sqlalchemy import select
from broker.base import Broker
from strategies import EMACrossStrategy, RSIReversionStrategy, MACDMomentumStrategy, MLPredictorStrategy, VolatilityBreakoutStrategy
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
            VolatilityBreakoutStrategy(),
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

            # Skip if outside market hours
            current_hour_utc = datetime.utcnow().hour
            if not (Config.TRADING_HOURS_START <= current_hour_utc < Config.TRADING_HOURS_END):
                logger.warning(f"Outside trading hours ({current_hour_utc}:00 UTC). Skipping cycle.")
                return

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
        """Check if drawdown exceeds limit (circuit breaker)."""
        account = await self.broker.get_account()
        if account['peak_value'] <= 0:
            logger.warning("Peak value is invalid, skipping drawdown check")
            return
        drawdown = (account['peak_value'] - account['portfolio_value']) / account['peak_value']

        if drawdown >= Config.MAX_DAILY_LOSS_PCT:
            logger.error(f"⛔ CIRCUIT BREAKER HIT: {drawdown*100:.2f}% >= {Config.MAX_DAILY_LOSS_PCT*100:.2f}%")
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
                    # Use NseIndiaApi for local paper trading
                    use_mock = Config.is_paper_mode()
                    price_data = await fetch_price(symbol, use_mock=use_mock)

                prices[symbol] = price_data['price']
                age_min = (datetime.utcnow() - price_data['timestamp']).total_seconds() / 60
                logger.info(f"{symbol}: ${price_data['price']:.2f} ({age_min:.1f}min old)")
            except Exception as e:
                logger.error(f"Failed to fetch {symbol}: {e}")

        if not prices:
            logger.warning("NO PRICES FETCHED - Cannot trade")
            return prices

        logger.info(f"Fetched {len(prices)} prices: {list(prices.keys())}")
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
        """Execute trade with confidence-weighted consensus."""
        buy_signals = [(name, s) for name, s in signals if s.direction == "BUY" and s.confidence >= 0.25]
        sell_signals = [(name, s) for name, s in signals if s.direction == "SELL" and s.confidence >= 0.25]

        buy_count = len(buy_signals)
        sell_count = len(sell_signals)
        buy_confidence = sum(s.confidence for _, s in buy_signals) / len(buy_signals) if buy_signals else 0
        sell_confidence = sum(s.confidence for _, s in sell_signals) / len(sell_signals) if sell_signals else 0

        if buy_count >= 1 and buy_confidence >= 0.25:
            logger.info(f"{symbol}: BUY signal ({buy_count} strategies, confidence={buy_confidence:.2f})")
            await self._place_buy_order(session, symbol, price)

        elif sell_count >= 1 and sell_confidence >= 0.25:
            logger.info(f"{symbol}: SELL signal ({sell_count} strategies, confidence={sell_confidence:.2f})")
            await self._place_sell_order(session, symbol, price)
        else:
            logger.debug(f"{symbol}: No consensus (BUY:{buy_count}@{buy_confidence:.2f}, SELL:{sell_count}@{sell_confidence:.2f})")

    async def _calculate_trade_stats(self, session):
        """Calculate win rate and avg win/loss from closed trades."""
        trades = (await session.execute(select(Trade))).scalars().all()

        if len(trades) < 10:
            return 0.52, 100, 100  # Default conservative stats

        winners = [t.net_pnl for t in trades if t.net_pnl > 0]
        losers = [abs(t.net_pnl) for t in trades if t.net_pnl < 0]

        if not winners or not losers:
            return 0.52, 100, 100

        win_rate = len(winners) / len(trades)
        avg_win = sum(winners) / len(winners) if winners else 100
        avg_loss = sum(losers) / len(losers) if losers else 100

        logger.info(f"Trade stats: Win rate={win_rate:.1%}, Avg win=${avg_win:.2f}, Avg loss=${avg_loss:.2f}")
        return win_rate, avg_win, avg_loss

    async def _place_buy_order(self, session, symbol, price):
        """Place a buy order if conditions met."""
        try:
            account = await self.broker.get_account()

            existing_pos = await session.execute(select(Position).where(Position.symbol == symbol))
            existing = existing_pos.scalar_one_or_none()
            if existing:
                logger.warning(f"{symbol}: Position already exists (qty={existing.qty}). Skipping new buy order.")
                return

            positions = await session.execute(select(Position))
            pos_list = positions.scalars().all()

            # Get real trade statistics
            win_rate, avg_win, avg_loss = await self._calculate_trade_stats(session)

            qty = PositionSizer.calculate_position_size(
                portfolio_value=account['portfolio_value'],
                cash=account['cash'],
                symbol=symbol,
                win_rate=win_rate,
                avg_win=avg_win,
                avg_loss=avg_loss,
                current_price=price,
                existing_positions={p.symbol: p for p in pos_list}
            )

            if qty <= 0:
                logger.warning(f"{symbol}: Cannot size position (qty={qty:.4f})")
                return

            order = await self.broker.place_order(
                symbol, "BUY", qty,
                stop_loss_pct=Config.STOP_LOSS_PCT,
                take_profit_pct=Config.TAKE_PROFIT_PCT
            )

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

            cost = qty * order.fill_price
            logger.info(f"{symbol}: BUY order filled. Qty={qty:.4f}, Price=${order.fill_price:.2f}, Cost=${cost:.2f}")

        except Exception as e:
            logger.error(f"{symbol}: Buy order failed: {e}")

    async def _place_sell_order(self, session, symbol, price):
        """Close existing position or short (if supported)."""
        try:
            pos_result = await session.execute(select(Position).where(Position.symbol == symbol))
            position = pos_result.scalar_one_or_none()

            if position:
                pnl = (price - position.avg_entry_price) * position.qty
                await self.broker.place_order(symbol, "SELL", position.qty)

                trade = Trade(
                    symbol=symbol,
                    side="SELL",
                    qty=position.qty,
                    fill_price=price,
                    gross_pnl=pnl,
                    net_pnl=pnl * (1 - Config.FEE_RATE),
                    strategy_name=position.strategy_name,
                    entry_trade_id=position.id
                )
                session.add(trade)
                session.delete(position)
                await session.commit()
                logger.info(f"{symbol}: Position closed. P&L: ${pnl:.2f}")

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
                        session.delete(pos)

                await session.commit()
                logger.info(f"Emergency close: {len(pos_list)} positions closed")

        except Exception as e:
            logger.error(f"Emergency close failed: {e}")

    async def _save_equity_snapshot(self):
        """Save current portfolio state."""
        try:
            account = await self.broker.get_account()
            if account['peak_value'] <= 0:
                drawdown = 0.0
            else:
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
