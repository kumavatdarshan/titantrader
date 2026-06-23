#!/usr/bin/env python3
"""
Weekend Backtest & Learning Script
Runs every 30 minutes on Saturday and Sunday via GitHub Actions.
- Downloads 1 year of real NSE historical data via NseIndiaApi
- Walks forward through it, running all strategies on each candle
- Simulates trades with slippage and fees, writes them to the DB
- Trains the ML model once enough trades are accumulated
- Prints a clean summary report at the end
"""
import asyncio
import logging
import sys
from datetime import datetime, timezone

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def _simulate_symbol(symbol: str, strategies: list, session_factory) -> dict:
    """
    Fetch 1 year of OHLCV data for one symbol, walk forward through the
    test window (last 25%), collect consensus signals from all strategies,
    simulate BUY/SELL trades, and write them to the database.

    Returns a summary dict for the symbol.
    """
    from data import fetch_ohlcv_candles
    from db import Trade
    from config import Config

    empty = {"symbol": symbol, "trades": 0, "win_rate": 0.0,
             "total_pnl": 0.0, "skipped": True}

    result = await fetch_ohlcv_candles(symbol, period="1y")
    if not result["success"] or result["data"] is None:
        logger.warning(f"[{symbol}] No data — {result.get('error', 'unknown')}")
        return empty

    df = result["data"].copy().reset_index(drop=True)
    logger.info(f"[{symbol}] {len(df)} candles ({result['source']})")

    if len(df) < 60:
        logger.warning(f"[{symbol}] Only {len(df)} candles, need 60 — skipping")
        return empty

    # First 75% = warmup so strategies have enough history.
    # Last 25% = the window we simulate trading on.
    warmup_end = int(len(df) * 0.75)
    test_slice = df.iloc[warmup_end:].reset_index(drop=True)

    slippage = Config.SLIPPAGE_BPS / 10_000   # e.g. 0.0002
    fee_rate = Config.FEE_RATE                 # e.g. 0.001
    capital_per_trade = Config.STARTING_CAPITAL * Config.MAX_POSITION_PCT

    open_position = None   # {entry_price, qty, strategy_name}
    pending_trades = []
    winning_closes = 0
    total_closed = 0
    total_pnl = 0.0

    for i in range(1, len(test_slice)):
        # Rolling price_df: all candles from the start up to current point
        price_df = df.iloc[: warmup_end + i].copy().reset_index(drop=True)
        current_price = float(test_slice.iloc[i]["Close"])

        # ── collect signals ───────────────────────────────────────────────
        buy_votes = 0
        sell_votes = 0
        lead_buy_strat = "consensus"
        lead_buy_conf = 0.0

        for strat in strategies:
            try:
                sig = await strat.generate_signal(symbol, price_df)
                if sig.direction == "BUY":
                    buy_votes += 1
                    if sig.confidence > lead_buy_conf:
                        lead_buy_conf = sig.confidence
                        lead_buy_strat = strat.name
                elif sig.direction == "SELL":
                    sell_votes += 1
            except Exception as e:
                logger.debug(f"[{symbol}] {strat.name} error at candle {i}: {e}")

        # ── consensus: at least 2 strategies must agree ───────────────────
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)

        if open_position is not None and sell_votes >= 2:
            # Close the open position
            entry = open_position["entry_price"]
            qty = open_position["qty"]
            fill = current_price * (1 - slippage)   # sell at slight discount
            gross = (fill - entry) * qty
            fee = fill * qty * fee_rate
            net = gross - fee

            total_pnl += net
            total_closed += 1
            if net > 0:
                winning_closes += 1

            pending_trades.append(Trade(
                timestamp=now_utc,
                symbol=symbol,
                side="SELL",
                qty=qty,
                fill_price=round(fill, 4),
                slippage_cost=round(abs(fill - current_price) * qty, 4),
                fee_cost=round(fee, 4),
                gross_pnl=round(gross, 4),
                net_pnl=round(net, 4),
                strategy_name=open_position["strategy_name"],
                exit_reason="backtest_signal",
            ))
            open_position = None

        elif open_position is None and buy_votes >= 2:
            # Open a new position
            fill = current_price * (1 + slippage)   # buy at slight premium
            if fill <= 0:
                logger.warning(f"[{symbol}] Invalid fill price {fill}, skipping")
                continue
            qty = round(capital_per_trade / fill, 4)
            if qty <= 0:
                continue

            open_position = {
                "entry_price": fill,
                "qty": qty,
                "strategy_name": lead_buy_strat,
            }
            pending_trades.append(Trade(
                timestamp=now_utc,
                symbol=symbol,
                side="BUY",
                qty=qty,
                fill_price=round(fill, 4),
                slippage_cost=round(abs(fill - current_price) * qty, 4),
                fee_cost=round(fill * qty * fee_rate, 4),
                gross_pnl=0.0,
                net_pnl=0.0,
                strategy_name=lead_buy_strat,
                exit_reason=None,
            ))

    # Force-close any position still open at end of test window
    if open_position is not None and len(test_slice) > 0:
        last_price = float(test_slice.iloc[-1]["Close"])
        entry = open_position["entry_price"]
        qty = open_position["qty"]
        gross = (last_price - entry) * qty
        fee = last_price * qty * fee_rate
        net = gross - fee

        total_pnl += net
        total_closed += 1
        if net > 0:
            winning_closes += 1

        pending_trades.append(Trade(
            timestamp=datetime.now(timezone.utc).replace(tzinfo=None),
            symbol=symbol,
            side="SELL",
            qty=qty,
            fill_price=round(last_price, 4),
            slippage_cost=0.0,
            fee_cost=round(fee, 4),
            gross_pnl=round(gross, 4),
            net_pnl=round(net, 4),
            strategy_name=open_position["strategy_name"],
            exit_reason="backtest_end",
        ))

    # Write all trades to DB in one session
    if pending_trades:
        async with session_factory() as session:
            for trade in pending_trades:
                session.add(trade)
            await session.commit()

    win_rate = winning_closes / total_closed if total_closed > 0 else 0.0
    logger.info(
        f"[{symbol}] {len(pending_trades)} trades written — "
        f"{total_closed} closed, WR={win_rate*100:.1f}%, "
        f"P&L=INR {total_pnl:+.2f}"
    )

    return {
        "symbol": symbol,
        "trades": total_closed,
        "win_rate": win_rate,
        "total_pnl": total_pnl,
        "skipped": False,
    }


async def main() -> int:
    logger.info("=" * 60)
    logger.info("TITANTRADER — WEEKEND BACKTEST & LEARNING")
    logger.info(f"Started at: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    logger.info("=" * 60)

    from config import Config
    from db import init_db, get_session_factory, Trade
    from strategies import (
        EMACrossStrategy,
        RSIReversionStrategy,
        MACDMomentumStrategy,
        VolatilityBreakoutStrategy,
        MLPredictorStrategy,
    )
    from backtester import Backtester
    from learner import Learner
    from sqlalchemy import select

    db_engine = await init_db()
    session_factory = get_session_factory(db_engine)

    strategies = [
        EMACrossStrategy(),
        RSIReversionStrategy(),
        MACDMomentumStrategy(),
        VolatilityBreakoutStrategy(),
        MLPredictorStrategy(),
    ]

    logger.info(f"Symbols   : {', '.join(Config.SYMBOLS)}")
    logger.info(f"Strategies: {[s.name for s in strategies]}")
    logger.info("-" * 60)

    # ── Phase 1: backtest every symbol ───────────────────────────────────────
    all_results = []
    for symbol in Config.SYMBOLS:
        try:
            res = await _simulate_symbol(symbol, strategies, session_factory)
            all_results.append(res)
        except Exception as e:
            logger.error(f"[{symbol}] Unexpected error: {e}", exc_info=True)
            all_results.append({"symbol": symbol, "trades": 0,
                                 "win_rate": 0.0, "total_pnl": 0.0, "skipped": True})

    # ── Phase 2: update strategy scores in DB ────────────────────────────────
    backtester = Backtester(session_factory)
    for res in all_results:
        if res["skipped"] or res["trades"] == 0:
            continue
        try:
            scores = {
                "symbol": res["symbol"],
                "win_rate": res["win_rate"],
                "total_trades": res["trades"],
                "total_pnl": res["total_pnl"],
                "avg_pnl": res["total_pnl"] / res["trades"],
                "max_drawdown": 0.0,
                "sharpe_ratio": 0.5 if res["win_rate"] >= 0.5 else 0.0,
            }
            async with session_factory() as session:
                await backtester._update_strategy_scores(session, scores)
                await session.commit()
        except Exception as e:
            logger.error(f"Strategy score update failed for {res['symbol']}: {e}")

    # ── Phase 3: ML training if enough trades ────────────────────────────────
    logger.info("-" * 60)
    try:
        async with session_factory() as session:
            result = await session.execute(select(Trade))
            trade_count = len(result.scalars().all())

        needed = Config.ML_MIN_TRADES_TO_TRAIN
        logger.info(f"Total trades in DB: {trade_count} (need {needed} for ML)")

        if trade_count >= needed:
            logger.info("Training ML model...")
            learner = Learner(session_factory)
            await learner.retrain_ml_model()
            logger.info("[OK] ML model trained and saved to models/predictor.pkl")
        else:
            logger.info(f"[SKIP] Need {needed - trade_count} more trades before ML training")
    except Exception as e:
        logger.error(f"ML training error: {e}", exc_info=True)

    # ── Phase 4: summary report ───────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("SUMMARY REPORT")
    logger.info("=" * 60)

    active = [r for r in all_results if not r["skipped"]]
    skipped = [r for r in all_results if r["skipped"]]

    for res in sorted(active, key=lambda x: x["win_rate"], reverse=True):
        flag = "[PASS]" if res["win_rate"] >= 0.5 else "[FAIL]"
        logger.info(
            f"{flag} {res['symbol']:<16} "
            f"WR={res['win_rate']*100:>5.1f}%  "
            f"Trades={res['trades']:>3}  "
            f"P&L=INR {res['total_pnl']:>+10.2f}"
        )

    if skipped:
        logger.info(f"Skipped (no/insufficient data): {[r['symbol'] for r in skipped]}")

    if active:
        avg_wr = sum(r["win_rate"] for r in active) / len(active)
        total_pnl = sum(r["total_pnl"] for r in active)
        total_trades = sum(r["trades"] for r in active)
        logger.info("-" * 60)
        logger.info(f"Symbols tested : {len(active)}")
        logger.info(f"Total trades   : {total_trades}")
        logger.info(f"Avg win rate   : {avg_wr*100:.1f}%")
        logger.info(f"Total sim P&L  : INR {total_pnl:+.2f}")

    logger.info("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
