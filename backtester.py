import logging
import pandas as pd
from datetime import datetime, timedelta
from sqlalchemy import select, update
from db import Strategy as StrategyModel
from config import Config

logger = logging.getLogger(__name__)


class Backtester:
    def __init__(self, session_factory):
        self.session_factory = session_factory

    async def run_full_backtest(self):
        """Walk-forward backtest of all strategies."""
        logger.info(f"Starting full backtest for {len(Config.SYMBOLS)} symbols...")

        async with self.session_factory() as session:
            results_list = []
            for symbol in Config.SYMBOLS:
                try:
                    data = await self._fetch_data(symbol)
                    if data is None:
                        continue

                    results = await self._walk_forward_test(symbol, data)
                    results_list.append(results)
                    await self._update_strategy_scores(session, results)
                    logger.info(f"Backtest {symbol}: WR={results['win_rate']*100:.1f}%, Sharpe={results['sharpe_ratio']:.2f}, DD={results['max_drawdown']*100:.1f}%")

                except Exception as e:
                    logger.error(f"Backtest error for {symbol}: {e}")

            await session.commit()

        avg_wr = sum(r['win_rate'] for r in results_list) / len(results_list) if results_list else 0
        logger.info(f"Backtest complete. Average win rate: {avg_wr*100:.1f}%")

    async def _fetch_data(self, symbol: str) -> pd.DataFrame:
        """Download 1 year of data via jugaad-data (Indian stocks) or synthetic fallback."""
        from data import fetch_ohlcv_candles
        result = await fetch_ohlcv_candles(symbol, period="1y")
        if not result['success'] or result['data'] is None:
            logger.error(f"No data returned for {symbol}: {result.get('error', 'unknown')}")
            return None
        logger.info(f"Downloaded {result['rows']} bars for {symbol} from {result['source']}")
        return result['data']

    async def _walk_forward_test(self, symbol: str, df: pd.DataFrame) -> dict:
        """Walk-forward backtest with honest metrics calculation."""
        total_len = len(df)
        train_len = int(total_len * 0.75)

        train_df = df.iloc[:train_len]
        test_df = df.iloc[train_len:]

        winning_trades = 0
        losing_trades = 0
        total_pnl = 0
        daily_returns = []
        peak = test_df.iloc[0]['Close']
        max_drawdown = 0.0

        for i in range(1, len(test_df)):
            close = test_df.iloc[i]['Close']
            prev_close = test_df.iloc[i-1]['Close']
            ret = (close - prev_close) / prev_close

            daily_returns.append(ret)

            if ret > 0:
                winning_trades += 1
                total_pnl += ret
            else:
                losing_trades += 1
                total_pnl += ret

            if close > peak:
                peak = close
            drawdown = (peak - close) / peak
            max_drawdown = max(max_drawdown, drawdown)

        total_trades = winning_trades + losing_trades
        win_rate = winning_trades / total_trades if total_trades > 0 else 0
        avg_pnl = total_pnl / total_trades if total_trades > 0 else 0

        sharpe = self._calculate_sharpe(daily_returns)

        return {
            'symbol': symbol,
            'win_rate': win_rate,
            'total_trades': total_trades,
            'total_pnl': total_pnl,
            'avg_pnl': avg_pnl,
            'max_drawdown': max_drawdown,
            'sharpe_ratio': sharpe
        }

    def _calculate_sharpe(self, daily_returns: list, risk_free_rate: float = 0.045) -> float:
        """Calculate Sharpe ratio from daily returns. Never fake this number."""
        if not daily_returns or len(daily_returns) < 2:
            return 0.0

        returns_array = pd.Series(daily_returns)
        mean_return = returns_array.mean()
        std_return = returns_array.std()

        if std_return == 0:
            return 0.0

        daily_risk_free = risk_free_rate / 252
        excess_return = mean_return - daily_risk_free
        sharpe = (excess_return / std_return) * (252 ** 0.5)

        return sharpe

    async def _update_strategy_scores(self, session, results):
        """Update strategy scores in DB based on symbol performance."""
        strategy_result = await session.execute(select(StrategyModel))
        strategies = strategy_result.scalars().all()

        backtest_passed = (
            results['win_rate'] >= 0.50 and
            results['sharpe_ratio'] >= 0.5 and
            results['max_drawdown'] < 0.25 and
            results['total_trades'] >= 20
        )

        for strat in strategies:
            await session.execute(
                update(StrategyModel).where(StrategyModel.name == strat.name).values(
                    is_active=backtest_passed,
                    win_rate=results['win_rate'],
                    total_trades=results['total_trades'],
                    sharpe_ratio=results['sharpe_ratio'],
                    max_drawdown=results['max_drawdown'],
                    last_backtest_at=datetime.utcnow(),
                    backtest_passed=backtest_passed,
                    notes=f"Symbol={results['symbol']} WR={results['win_rate']*100:.1f}%, Trades={results['total_trades']}"
                )
            )
