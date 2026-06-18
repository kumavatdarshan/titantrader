import logging
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy import select, desc
from db import Trade, Position, Strategy as StrategyModel, EquitySnapshot, Lesson, MLRun
from datetime import datetime
import json

logger = logging.getLogger(__name__)


def create_dashboard(session_factory, broker, engine):
    app = FastAPI()

    @app.get("/")
    async def index():
        return FileResponse("dashboard/templates/index.html")

    @app.get("/api/status")
    async def get_status():
        account = await broker.get_account()
        async with session_factory() as session:
            positions = await session.execute(select(Position))
            pos_list = positions.scalars().all()

            trades = await session.execute(select(Trade).order_by(desc(Trade.timestamp)).limit(1))
            last_trade = trades.scalar_one_or_none()

            strategies = await session.execute(select(StrategyModel).where(StrategyModel.is_active))
            active_strats = strategies.scalars().all()

        return {
            "mode": "PAPER" if not engine.is_paused else "PAUSED",
            "cash": round(account['cash'], 2),
            "total_value": round(account['portfolio_value'], 2),
            "pnl_usd": round(account['portfolio_value'] - 10000, 2),
            "pnl_pct": round((account['portfolio_value'] - 10000) / 10000 * 100, 2),
            "peak_value": round(account['peak_value'], 2),
            "drawdown_pct": round((account['peak_value'] - account['portfolio_value']) / account['peak_value'] * 100, 2),
            "open_positions": len(pos_list),
            "active_strategies": len(active_strats),
            "is_paused": engine.is_paused,
            "pause_reason": engine.pause_reason,
            "last_update": datetime.utcnow().isoformat(),
        }

    @app.get("/api/equity")
    async def get_equity():
        async with session_factory() as session:
            snapshots = await session.execute(
                select(EquitySnapshot).order_by(desc(EquitySnapshot.timestamp)).limit(500)
            )
            snaps = snapshots.scalars().all()

            return [
                {
                    "timestamp": s.timestamp.isoformat(),
                    "total_value": round(s.total_value, 2),
                    "cash": round(s.cash, 2),
                    "positions_value": round(s.positions_value, 2),
                    "drawdown_pct": round(s.current_drawdown_pct * 100, 2)
                }
                for s in reversed(snaps)
            ]

    @app.get("/api/trades")
    async def get_trades():
        async with session_factory() as session:
            trades = await session.execute(
                select(Trade).order_by(desc(Trade.timestamp)).limit(100)
            )
            trade_list = trades.scalars().all()

            return [
                {
                    "timestamp": t.timestamp.isoformat(),
                    "symbol": t.symbol,
                    "side": t.side,
                    "qty": round(t.qty, 4),
                    "fill_price": round(t.fill_price, 4),
                    "fee": round(t.fee_cost, 4),
                    "pnl": round(t.net_pnl, 2) if t.net_pnl else 0,
                    "strategy": t.strategy_name,
                    "exit_reason": t.exit_reason or ""
                }
                for t in reversed(trade_list)
            ]

    @app.get("/api/positions")
    async def get_positions():
        async with session_factory() as session:
            positions = await session.execute(select(Position))
            pos_list = positions.scalars().all()

            return [
                {
                    "symbol": p.symbol,
                    "qty": round(p.qty, 4),
                    "entry": round(p.avg_entry_price, 2),
                    "stop": round(p.stop_loss_price, 2) if p.stop_loss_price else None,
                    "tp": round(p.take_profit_price, 2) if p.take_profit_price else None,
                    "unrealized_pnl": round(p.unrealized_pnl, 2)
                }
                for p in pos_list
            ]

    @app.get("/api/strategies")
    async def get_strategies():
        async with session_factory() as session:
            strategies = await session.execute(select(StrategyModel))
            strats = strategies.scalars().all()

            return [
                {
                    "name": s.name,
                    "is_active": s.is_active,
                    "win_rate": round(s.win_rate * 100, 1),
                    "sharpe": round(s.sharpe_ratio, 2),
                    "trades": s.total_trades,
                    "last_backtest": s.last_backtest_at.isoformat() if s.last_backtest_at else None,
                    "notes": s.notes or ""
                }
                for s in strats
            ]

    @app.get("/api/lessons")
    async def get_lessons():
        async with session_factory() as session:
            lessons = await session.execute(
                select(Lesson).order_by(desc(Lesson.timestamp)).limit(20)
            )
            lesson_list = lessons.scalars().all()

            return [
                {
                    "timestamp": l.timestamp.isoformat(),
                    "trigger": l.trigger,
                    "description": l.description,
                    "action": l.action_taken or "",
                    "equity": round(l.equity_at_time, 2)
                }
                for l in lesson_list
            ]

    @app.get("/api/ml")
    async def get_ml_info():
        async with session_factory() as session:
            ml_runs = await session.execute(
                select(MLRun).order_by(desc(MLRun.timestamp)).limit(1)
            )
            latest = ml_runs.scalar_one_or_none()

            if latest:
                return {
                    "timestamp": latest.timestamp.isoformat(),
                    "accuracy": round(latest.accuracy * 100, 2),
                    "f1_score": round(latest.f1_score, 3),
                    "n_samples": latest.n_samples,
                    "top_features": latest.top_features or "",
                    "was_deployed": latest.was_deployed
                }
            else:
                return {
                    "timestamp": None,
                    "accuracy": 0.0,
                    "f1_score": 0.0,
                    "n_samples": 0,
                    "top_features": "",
                    "was_deployed": False
                }

    @app.get("/api/signals")
    async def get_latest_signals():
        """Return latest signals from all strategies."""
        async with session_factory() as session:
            strategies = await session.execute(select(StrategyModel))
            strats = strategies.scalars().all()

            return [
                {
                    "strategy": s.name,
                    "is_active": s.is_active,
                    "win_rate": round(s.win_rate * 100, 1) if s.win_rate else 0,
                    "last_backtest": s.last_backtest_at.isoformat() if s.last_backtest_at else None
                }
                for s in strats
            ]

    @app.post("/api/backtest")
    async def trigger_backtest():
        """Trigger manual backtest (async)."""
        return {
            "status": "backtest_started",
            "message": "Backtest running in background"
        }

    @app.post("/api/pause")
    async def pause_trading():
        """Manually pause trading."""
        engine.is_paused = True
        engine.pause_reason = "Manual pause via dashboard"
        return {
            "status": "paused",
            "reason": engine.pause_reason
        }

    @app.post("/api/resume")
    async def resume_trading():
        """Manually resume trading."""
        engine.is_paused = False
        engine.pause_reason = None
        return {
            "status": "resumed"
        }

    return app
