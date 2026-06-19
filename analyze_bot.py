from datetime import datetime
from pathlib import Path

print("=" * 80)
print("TITANTRADER BOT ANALYSIS - WHAT'S WORKING & WHAT'S BROKEN")
print("=" * 80)

db_exists = Path("titantrader.db").exists()
models_exist = Path("models/predictor.pkl").exists()
logs_exist = Path("logs").exists()

print("\n📊 CURRENT STATE:")
print("✓ Trading Mode: Alpaca Paper (ready to go live)")
print("✓ Symbols: AAPL, TSLA, NVDA, SPY, MSFT (5 high-liquid stocks)")
print("✓ Capital: $10,000 (testing mode)")
print("✓ Strategies: 5 (EMA, RSI, MACD, Volatility, ML)")

print(f"\n📁 FILES:")
print(f"{'✓' if db_exists else '✗'} Database: titantrader.db - {'exists' if db_exists else 'MISSING (first run)'}")
print(f"{'✓' if models_exist else '✗'} ML Model: models/predictor.pkl - {'trained' if models_exist else 'not trained yet'}")
print(f"{'✓' if logs_exist else '✗'} Logs: logs/ - {'exists' if logs_exist else 'MISSING'}")

print("\n🔴 CRITICAL ISSUES (Preventing Profits):")
print("""
1. ML FEATURE MISMATCH (MOST CRITICAL)
   ✗ Trains on: qty, fees, slippage, fill_price, hour, day
   ✗ Predicts with: volume, volatility, price, hour, day
   → Bot can't learn patterns because features don't match
   → Model predicts "profit" based on ORDER SIZE, not market conditions
   → This is WHY your bot isn't profitable

2. DATA LEAKAGE IN LIVE TRADING
   ✗ Feature extraction uses: pd.Timestamp.now().hour
   → Hour/day are REAL-TIME, not the trade entry time
   → Model "sees the future" in production

3. INCOMPLETE BACKTESTING
   ✗ Only backtests 3 symbols (first 3)
   ✗ You're trading 5 symbols - 2 untested!
   ✗ No walk-forward validation (trains and tests on overlapping data)

4. WEAK DATA PIPELINE
   ✗ Only uses 30 days of price history
   ✗ Signals generated from insufficient data
   ✗ Falls back to synthetic/mock data masks real issues

5. ARBITRARY THRESHOLDS
   ✗ Confidence threshold: 0.30 (why? pulled from air)
   ✗ ML accuracy minimum: 0.55 (too low, fits noise)
   ✗ Position limit: 5 (no optimization)
""")

print("\n🟢 WHAT'S WORKING:")
print("""
1. ✓ Multi-strategy consensus (reduces false signals)
2. ✓ Drawdown protection (stops bleeding)
3. ✓ Database logging (can analyze trades)
4. ✓ Alpaca integration (real broker, real data)
5. ✓ Scheduled retraining (adapts to market)
6. ✓ Kelly Criterion sizing (mathematically sound)
""")

print("\n⚠️  MARKET HOURS (IST = India Standard Time):")
print("""
Trading Window: 7 PM - 1 AM IST (13:30-20:00 UTC)
ML Retrain: 2 AM IST
Trade Interval: Every 5 minutes
Issues: Only retrained once per day (too slow)
""")

print("\n💰 WHY YOU'RE NOT SEEING PROFITS YET:")
print("""
1. ML model is broken (features mismatch) → Random predictions
2. Insufficient backtesting → Trading untested strategies  
3. Data leakage → Model thinks it knows the future
4. Arbitrary thresholds → Too many false signals
5. Not tested live with real money yet
""")
