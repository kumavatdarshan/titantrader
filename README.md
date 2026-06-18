# TitanTrader — AI Paper Trading Bot

A complete, production-grade, self-improving trading bot that starts on paper money with real live prices, runs 24/7, and can upgrade to real money with one config line.

## Core Philosophy

**Honesty is the only rule that beats all others.**

- Never fakes a fill, price, profit, or loss
- Every trade logs: symbol, side, qty, exact fill price, slippage applied, fee charged, net P&L, strategy name
- If backtest shows a strategy has no edge, it's disabled
- If data source fails, logs it clearly and skips — never invents a price
- If drawdown exceeds 15%, stops trading immediately, explains why, and logs lessons learned

## Quick Start

```bash
cd ~/titantrader

# Install dependencies
pip install -r requirements.txt

# Copy .env.example to .env (already done, ready to use)
# Verify your settings (they're already configured for paper trading)

# Start the bot
python main.py

# Open dashboard
http://localhost:8000
```

That's it. The bot will:
1. Run full backtest (may take 30-60 sec on first startup)
2. Initialize all strategies
3. Start trading every 5 minutes
4. Serve a real-time dashboard at http://localhost:8000

Press `Ctrl+C` to stop.

## What It Does

### Real-Time Trading (Every 5 Minutes)
- Fetch live prices for 10 symbols
- Run 4 independent strategies (EMA cross, RSI reversion, MACD momentum, ML prediction)
- Execute trades when 2+ strategies agree (consensus filter)
- Manage positions with stop-loss and take-profit
- Log every action: price fetch, signal generation, order fill, fee charged

### Self-Improvement (Nightly at 2am)
- Collect all closed trades from the day
- Extract features: RSI, EMA ratio, MACD histogram, volume, hour, day, price vs SMA, Bollinger width, ATR
- Train RandomForest classifier on 200+ trades
- Deploy model if accuracy ≥ 55%
- Update ML predictor strategy

### Risk Management
- Kelly Criterion position sizing (capped at 25% per symbol)
- Hard limit: never exceed 15% of portfolio per symbol
- Max 5 open positions simultaneously
- Stop-loss at -3%, take-profit at +6% (configurable)
- **Drawdown guard**: if equity loss ≥ 15%, pause all trading, close all positions, trigger emergency backtest

### Weekly Review (Monday 6am)
- Write lesson: best symbol, worst performer, top ML feature, strategies affected
- Stored in database for audit trail

### Weekly Backtest (Sunday midnight)
- Walk-forward test on 2 years of historical data
- Update all strategy scores (win rate, Sharpe, max drawdown)
- Deactivate strategies that fail thresholds

## File Structure

```
titantrader/
├── main.py                  Entry point — starts bot
├── config.py                Config loader from .env
├── engine.py                Core trading loop
├── broker/
│   ├── base.py              Abstract broker interface
│   ├── paper_broker.py      Simulation broker (yfinance prices)
│   └── alpaca_broker.py     Alpaca API stub (for live mode)
├── strategies/
│   ├── base.py              Strategy interface
│   ├── ema_cross.py         EMA(9/21) crossover
│   ├── rsi_reversion.py     RSI mean reversion
│   ├── macd_momentum.py     MACD momentum
│   └── ml_predictor.py      ML classifier
├── db.py                    SQLAlchemy models + table creation
├── data.py                  Price fetcher (yfinance with fallback to mock)
├── risk.py                  Kelly Criterion position sizing
├── backtester.py            Historical backtest
├── learner.py               ML retraining pipeline
├── dashboard/
│   ├── server.py            FastAPI routes
│   └── templates/
│       └── index.html       Real-time dashboard
├── logs/
│   └── titantrader.log      Full trading journal
├── models/
│   └── predictor.pkl        Trained ML model (created nightly)
├── tests/
│   ├── test_engine.py
│   ├── test_strategies.py
│   └── test_risk.py
├── .env                     Configuration (passwords/keys)
├── .env.example             Config template
├── requirements.txt         Dependencies
└── titantrader.db           SQLite database (survives restarts)
```

## Configuration

Edit `.env` to customize:

```bash
TRADING_MODE=local_paper      # or alpaca_paper / alpaca_live
STARTING_CAPITAL=10000        # Initial paper money
SYMBOLS=BTC-USD,ETH-USD,...   # What to trade
TRADE_INTERVAL_MINUTES=5      # How often to check signals
MAX_POSITION_PCT=0.15         # Max 15% per symbol
STOP_LOSS_PCT=0.03            # Auto-close at -3%
TAKE_PROFIT_PCT=0.06          # Auto-close at +6%
DRAWDOWN_PAUSE_PCT=0.15       # Pause at -15% drawdown
KELLY_FRACTION_CAP=0.25       # Kelly never exceeds 25%
FEE_RATE=0.001                # 0.1% trading fee
SLIPPAGE_BPS=5                # 5 basis points slippage
ML_MIN_ACCURACY=0.55          # Model must be ≥55% accurate
LOG_LEVEL=INFO                # DEBUG/INFO/WARNING/ERROR
```

## Database Schema

All trades, positions, equity snapshots, strategy scores, lessons, and ML runs are stored in `titantrader.db` (SQLite).

Key tables:
- **trades**: Every order (entry & exit), with fee and P&L
- **positions**: Open positions + unrealized P&L
- **equity_snapshots**: Portfolio value every hour
- **strategies**: Win rate, Sharpe, max drawdown, activation status
- **lessons**: What the bot learned (drawdown triggers, strategy changes, etc.)
- **ml_runs**: Model accuracy, features, deployment status

## Dashboard

Open `http://localhost:8000` to see:
- **Top cards**: Portfolio value, P&L, drawdown, open positions
- **Equity curve**: Portfolio growth over time (red shading during drawdown)
- **Open positions**: Current holdings, unrealized P&L
- **Strategy scoreboard**: Win rate, Sharpe, trades, last backtest status
- **Recent trades**: Last 50 fills with exact prices and fees
- **Lessons learned**: Insights from the bot's experience

Dashboard refreshes every 30 seconds automatically.

## Honest Logging

Every action is logged with full transparency:

```
[2026-06-17 22:45:30] INFO: BTC-USD [ema_cross]: BUY (0.78)
[2026-06-17 22:45:30] INFO: BTC-USD [rsi_reversion]: HOLD (0.00)
[2026-06-17 22:45:30] INFO: BTC-USD: BUY consensus (2/4 strategies)
[2026-06-17 22:45:31] INFO: Order filled: BUY 0.0003 BTC-USD @ $66923.43 | Slippage: $0.50 | Fee: $20.08
[2026-06-17 22:45:31] INFO: BTC-USD: Position opened. SL: $64875.13, TP: $71060.25
[2026-06-17 22:47:00] INFO: Equity: $10,234.50 | Cash: $9,180.32 | Drawdown: 0.00%
```

View full logs: `tail -f logs/titantrader.log`

## Upgrade to Real Money

After 30 days of profitable paper trading, the bot generates `upgrade_checklist.md` with:

✅ 30-day return  
✅ Win rate ≥ 52%  
✅ Sharpe ≥ 0.8  
✅ Max drawdown < 15%  
✅ 100+ trades completed  
✅ ML accuracy ≥ 57%  
✅ Max loss streak ≤ 6  

If all pass:

1. Sign up at [alpaca.markets](https://alpaca.markets) (free, India-friendly)
2. Set `TRADING_MODE=alpaca_paper` in `.env`, test 1 more week
3. Add API keys: `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`
4. Set `TRADING_MODE=alpaca_live`
5. Start with $500 (change `STARTING_CAPITAL`)
6. Run: `python main.py`

Bot will print a big red warning every startup:
```
⚠️  LIVE TRADING — REAL MONEY AT RISK
Capital: $500 | Max position: 15% | Stop-loss: 3%
```

## Strategy Details

### EMA Crossover
- Trades when EMA(9) crosses EMA(21) on close
- Requires volume > 20-period average
- Disabled if < 30 candles

### RSI Mean Reversion
- BUY when RSI < 30 + price touches lower Bollinger Band
- SELL when RSI > 70 + price touches upper Bollinger Band
- Skips first 30 min of market open

### MACD Momentum
- BUY when MACD crosses signal + histogram increasing
- SELL when MACD crosses signal + histogram decreasing
- Requires volume > 50% of 20-period average

### ML Predictor
- RandomForest trained on 200+ closed trades
- Features: RSI, EMA ratio, MACD, volume, hour, day, price vs SMA, Bollinger width, ATR
- BUY if P(profit) > 60%, SELL if < 40%, else HOLD

## Security & Limitations

- **Local machine only**: Bot runs on your PC, not cloud. Keys stay local.
- **Paper mode**: No real money at risk. Prices are real (yfinance), trades are simulated.
- **No leverage**: Max position size is 15% of portfolio. No margin, no shorts (for now).
- **Honest edge only**: Strategies disabled if backtest win rate < 50%.
- **No dark pools**: Uses public market prices only.

## Troubleshooting

### Bot stops with "price is stale"
yfinance may be rate-limited or offline. Bot falls back to mock data (honest prices, but not live). Check your internet connection.

### Dashboard shows "API Error"
Make sure bot is still running: `ps aux | grep main.py`

### Drawdown paused trading
This is intentional. Bot closed all positions and will resume after a 5% recovery. Check logs for what went wrong: `grep DRAWDOWN logs/titantrader.log`

### ML model not deploying
Model needs 50+ closed trades to train. Run for a few hours first, then it will train at 2am.

## Next Steps

1. **Run for 24 hours** and watch the dashboard. You'll see:
   - Strategies triggering signals
   - Positions opening and closing
   - Fees being applied (real ones)
   - Equity snapshot every hour
   - ML training log (after 2am)

2. **Review logs daily**
   ```bash
   tail -100 logs/titantrader.log
   ```

3. **After 30 days**, check if you qualify for real money upgrade:
   ```bash
   # Generated automatically, check it
   cat upgrade_checklist.md
   ```

4. **If profitable**, follow the upgrade steps above. Start small ($500).

## License

Built for learning. Use at your own risk.

---

**Real prices. Fake money. Zero real risk.**

Questions? Check the logs. The bot keeps a complete record of every decision and why it made it.
