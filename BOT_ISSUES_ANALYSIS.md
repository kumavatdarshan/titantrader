# TitanTrader Bot - Critical Issues & Flaws Analysis

**Generated:** 2026-06-23

---

## 🔴 CRITICAL ISSUES (Must Fix)

### 1. **Trading Hours Config Mismatch - MAJOR BUG**
**File:** `config.py:25-26`
```python
TRADING_HOURS_START = 4   # 9:30 AM IST
TRADING_HOURS_END = 9     # 2:30 PM IST (WRONG!)
```

**Problem:** 
- NSE closes at **3:30 PM IST (10 AM UTC)**, but `TRADING_HOURS_END = 9` stops trading at **2:30 PM IST**
- This causes the bot to **miss the last hour of trading** every day
- The engine.py (line 39) uses this to skip trading cycles after 9 AM UTC

**Impact:** 
- Lost 1 hour of daily trading opportunity
- Can't capitalize on late-day trends
- Recent workflow fix was correct but config wasn't updated

**Fix:**
```python
TRADING_HOURS_START = 4   # 9:30 AM IST (4 AM UTC)
TRADING_HOURS_END = 10    # 3:30 PM IST (10 AM UTC) ← CHANGE THIS
```

---

### 2. **Missing Entry Trade Records - DB Corruption**
**Files:** `engine.py:180-257`, `db.py`

**Problem:**
- When a **BUY order is placed**, NO trade record is created in the `trades` table
- Only a `Position` record is stored
- When the position is closed (SELL), the Trade record contains `entry_trade_id` (line 280) pointing to a non-existent trade
- This breaks the entry/exit relationship and causes orphaned records

**Impact:**
- Cannot track actual trade pairs (entry→exit)
- Corrupts trade statistics and P&L calculations
- ML training data is incomplete

**Fix:** Create a Trade record for BUY orders:
```python
# In _place_buy_order() after successful order execution:
entry_trade = Trade(
    symbol=symbol,
    side="BUY",
    qty=qty,
    fill_price=order.fill_price,
    gross_pnl=0,
    net_pnl=0,
    strategy_name="consensus"
)
session.add(entry_trade)
await session.commit()
# Then use entry_trade.id in Position.entry_trade_id
```

---

### 3. **Kelly Criterion Wrong Input Data**
**File:** `risk.py:64`

**Problem:**
```python
if len(existing_positions) < Config.MIN_KELLY_TRADES:  # WRONG!
```
- `existing_positions` is a dict of **current open positions** (not historical trades)
- Should check **historical trade count** from database
- `existing_positions` has ~0-5 items, always less than `MIN_KELLY_TRADES` (30)
- Result: Kelly criterion is never used, always falls back to 50% Kelly

**Impact:**
- Position sizing is always conservative, using 50% fractional Kelly instead of calculated Kelly
- Underutilized positions, leaving money on the table
- Loss of optimal sizing when strategy has good historical win rate

**Fix:**
```python
# Before calling calculate_position_size, fetch trade count:
async with self.session_factory() as session:
    result = await session.execute(select(func.count(Trade.id)))
    total_trades = result.scalar() or 0

# Then pass to PositionSizer:
if total_trades < Config.MIN_KELLY_TRADES:
    kelly_fraction = Config.KELLY_FRACTION_CAP * 0.5
```

---

### 4. **Inconsistent P&L Calculation - Entry Side Missing Slippage**
**Files:** `engine.py:269-278`, `paper_broker.py:68-96`

**Problem:**
- **Sell-side P&L:**
```python
pnl = (price - position.avg_entry_price) * position.qty
net_pnl = pnl * (1 - Config.FEE_RATE)
```
- This subtracts **fees but NOT slippage**
- Entry side slippage is paid in `paper_broker.py` when buying, but not reflected in P&L
- Example: If you buy at $100 (with 2 bps slippage = $100.02 actual cost), the `avg_entry_price` stored is $100, not $100.02

**Impact:**
- P&L overstated by 2-4 bps per round-trip (buy + sell slippage)
- Long-running strategies accumulate significant P&L inflation
- Inflates strategy performance metrics and false confidence

**Fix:**
```python
# In engine.py _place_sell_order():
# Account for all costs in P&L
slippage_on_exit = price * (Config.SLIPPAGE_BPS / 10000) * position.qty
fee = price * position.qty * Config.FEE_RATE
net_pnl = (price - position.avg_entry_price) * position.qty - slippage_on_exit - fee
```

---

### 5. **Broker Order Failure = Silent Database Corruption**
**File:** `engine.py:262-288`

**Problem:**
```python
# Line 270: Place sell order
await self.broker.place_order(symbol, "SELL", position.qty)

# Line 283: Delete position from DB
session.delete(position)
await session.commit()
```

- If `broker.place_order()` **raises an exception**, the code catches it (line 287)
- But the **position is still deleted from the database!**
- Order failed → position no longer exists → bot thinks it closed a position it didn't

**Impact:**
- Actual trade on broker ≠ database state
- Corrupted portfolio accounting
- Next cycle will be confused about cash/positions

**Fix:**
```python
try:
    order = await self.broker.place_order(symbol, "SELL", position.qty)
    # Only delete AFTER successful order
    session.delete(position)
    await session.commit()
    # Log successful close
except Exception as e:
    logger.error(f"{symbol}: Sell order failed: {e}")
    # Keep position open, will retry next cycle
    return
```

---

### 6. **ML Model File Not Found = Silent Failure**
**File:** `strategies/ml_predictor.py:20-37`

**Problem:**
```python
def _load_model(self):
    model_path = Path("models/predictor.pkl")
    if model_path.exists():  # ← If path doesn't exist, just silently skip
        # ... load model
    # No error if model doesn't exist
```

- If model file doesn't exist (first run, corrupted file, wrong path), it silently sets `self.model = None`
- Strategy generates HOLD signals instead of actual predictions
- No warning that ML strategy is completely disabled

**Impact:**
- ML strategy (5th strategy) never generates signals
- Consensus threshold becomes harder to reach (4 strategies instead of 5)
- Bot trades with degraded performance silently

**Fix:**
```python
def _load_model(self):
    model_path = Path("models/predictor.pkl")
    if not model_path.exists():
        logger.warning(f"ML model not found at {model_path}. Model will not be deployed.")
        self.model = None
        return
    
    try:
        with open(model_path, 'rb') as f:
            # ... load
    except Exception as e:
        logger.error(f"CRITICAL: Failed to load ML model: {e}")
        self.model = None
```

---

### 7. **Learner.py Has Undefined Variable**
**File:** `learner.py:69`

**Problem:**
```python
with open(model_path, 'wb') as f:
    pickle.dump({'model': model, 'scaler': scaler}, f)
    # ← 'scaler' is never defined!
```

- The code tries to save `scaler` but it's never created in `retrain_ml_model()`
- This will crash the ML training pipeline

**Impact:**
- ML training always fails when trying to save
- ML models are never deployed
- ML strategy permanently disabled

**Fix:**
```python
# Add before fitting model:
from sklearn.preprocessing import StandardScaler
scaler = StandardScaler()
X_scaled = scaler.fit_transform(X_train)
model.fit(X_scaled, y_train)

# Then save:
pickle.dump({'model': model, 'scaler': scaler}, f)
```

---

### 8. **Correlation Check Ignores .NS Suffix**
**File:** `risk.py:88-113`

**Problem:**
```python
tech_symbols = {'AAPL', 'MSFT', 'NVDA', 'GOOGL', 'META'}
held_tech = [s for s in positions.keys() if s in tech_symbols]

it_symbols = {'INFY', 'TCS', 'WIPRO', 'HCLTECH', 'TECHM'}
held_it = [s for s in positions.keys() if s in it_symbols]
```

- Config stores symbols as `TCS.NS`, `INFY.NS` (with .NS suffix)
- Correlation check uses bare names `TCS`, `INFY` (without suffix)
- Positions dict keys have .NS, but hardcoded sets don't
- Result: Correlation check never matches any Indian IT stocks!

**Impact:**
- Correlation limit on Indian IT sector is **never enforced**
- Bot can hold 5 IT stocks at once (all highly correlated)
- Massive concentration risk undetected

**Fix:**
```python
it_symbols = {'INFY', 'INFY.NS', 'TCS', 'TCS.NS', 'WIPRO', 'WIPRO.NS', 'HCLTECH', 'HCLTECH.NS', 'TECHM', 'TECHM.NS'}
# OR better:
def _normalize_symbol(s):
    return s[:-3] if s.endswith('.NS') else s

held_it = [s for s in positions.keys() if _normalize_symbol(s) in it_symbols]
```

---

### 9. **Stale Price Not Detected for Trading**
**Files:** `engine.py:48-110`, `paper_broker.py:75-76`

**Problem:**
- `paper_broker.py` has a check: If price is >10 min old, raise `DataUnavailableError`
- But `engine.py` catches **all exceptions** silently (line 103)
- A stale price causes the symbol to be skipped, but no warning is logged clearly

**Impact:**
- Silent skip of symbols due to stale data (no clear error in logs)
- Trades might not execute when intended
- Hard to debug why a symbol didn't trade

**Fix:**
```python
# In engine.py _fetch_all_prices():
except DataUnavailableError as e:
    logger.warning(f"{symbol}: STALE DATA - {e}")  # Clearer warning
except Exception as e:
    logger.error(f"{symbol}: Failed to fetch - {e}")
```

---

## 🟡 MAJOR ISSUES (High Priority)

### 10. **Empty Consensus Signals List Bug**
**File:** `engine.py:147-148`

**Problem:**
```python
buy_confidence = sum(s.confidence for _, s in buy_signals) / len(buy_signals) if buy_signals else 0
```
- If `buy_signals` is empty, this correctly returns 0
- But earlier (line 142), signals are already filtered: `if s.confidence >= 0.45`
- If all 5 strategies vote BUY but below 0.45 confidence, then `buy_signals = []` and `buy_confidence = 0`
- The line 150 check `if buy_count >= 2 and buy_confidence >= 0.45:` will fail (0 >= 0.45 is False)
- This is correct logic but can be confusing

**Impact:** Minor - logic is actually correct, but code clarity issue

**Fix:** Add explicit comment:
```python
# Only signals with confidence >= 0.45 pass filter
buy_signals = [(name, s) for name, s in signals if s.direction == "BUY" and s.confidence >= 0.45]
buy_count = len(buy_signals)
buy_confidence = sum(s.confidence for _, s in buy_signals) / buy_count if buy_count > 0 else 0.0
```

---

### 11. **Feature Leakage in ML Training**
**File:** `learner.py:105-118` (in ml_predictor.py), specifically the `hour` and `day` features

**Problem:**
- ML model is trained with `hour` and `day_of_week` features (from current time)
- During training, these represent historical times when trades occurred
- When generating predictions on live data, these features represent the **current time**
- This is a subtle form of **forward-looking bias** - the model learns to depend on time-of-day patterns that may not be stable

**Impact:**
- ML model may overfit to specific hours (e.g., "always buy at 9:30 AM")
- Performance degrades at other times
- Model confidence misleading

**Fix:**
```python
# Remove or normalize hour/day features, or use relative time from market open:
market_open_utc = 4  # 9:30 AM IST = 4 AM UTC
minutes_since_open = (hour - market_open_utc) * 60 + minute
features = [
    rsi, macd, ...,
    minutes_since_open,  # Relative time, not absolute
    # Remove day_of_week to prevent weekly seasonality overfitting
]
```

---

### 12. **Position Entry Not Tracked Properly**
**File:** `engine.py:245-254`

**Problem:**
```python
new_pos = Position(
    symbol=symbol,
    qty=qty,
    avg_entry_price=order.fill_price,  # ← This is already slippage-adjusted
    ...
)
```

- `order.fill_price` is already adjusted for slippage in `paper_broker.place_order()`
- But the actual cost to the cash account is `fill_price + fee`
- So `avg_entry_price` doesn't match the actual cash impact
- This breaks P&L calculations later

**Impact:**
- P&L calculations are off
- Positions show wrong breakeven price

**Fix:**
```python
# Store the actual cost price, not the market fill price
cost_price = order.fill_price + (order.fill_price * Config.FEE_RATE / qty) if qty > 0 else order.fill_price
new_pos = Position(
    symbol=symbol,
    qty=qty,
    avg_entry_price=cost_price,
    ...
)
```

---

### 13. **Uninitialized Equity Snapshot Peak Value**
**File:** `paper_broker.py:18-23`

**Problem:**
- `PaperBroker.__init__()` sets `peak_value = starting_capital`
- But this only happens once at init
- If bot runs for first time with a position, peak_value might not update correctly

**Impact:**
- Drawdown calculation could be wrong on first day
- Minor, but could cause false circuit breaker triggers

**Fix:** Ensure peak_value is recalculated:
```python
async def get_account(self) -> dict:
    total_value = self.cash + positions_value
    if total_value > self.peak_value:
        self.peak_value = total_value
    # ... rest of code
```

---

### 14. **No Overnight Gap Handling**
**Files:** `engine.py`, `paper_broker.py`

**Problem:**
- Bot closes all positions at 9 AM UTC (line 26: `TRADING_HOURS_END = 9`)
- Actually NO - bot stops TRADING at 9 AM but doesn't close positions!
- Positions remain open overnight
- NSE closes at 3:30 PM IST (10 AM UTC)
- Price next day could gap significantly
- Position's `stop_loss_price` and `take_profit_price` might be unrealistic

**Impact:**
- Overnight risk is unmanaged
- Stop losses might not execute as expected
- Could wake up to massive losses

**Fix:**
```python
# Add code to close all positions at market close
async def close_positions_at_market_close(self):
    """Close all positions at NSE market close."""
    if datetime.utcnow().hour >= 10:  # 3:30 PM IST
        await self._close_all_positions()
```

---

### 15. **Database Session Not Always Closed**
**File:** `engine.py` - multiple places

**Problem:**
- Code uses `async with self.session_factory() as session:` in most places ✓
- But in some functions (e.g., `_calculate_trade_stats`), session might not commit properly if exception occurs
- SQLite in local_paper mode might lock on concurrent access

**Impact:**
- Minor for local_paper, but critical for production
- Potential database locks

**Fix:** Ensure all sessions have try/except:
```python
async with self.session_factory() as session:
    try:
        result = await session.execute(...)
        await session.commit()
    except Exception as e:
        logger.error(f"DB error: {e}")
        await session.rollback()
        raise
```

---

## 🟠 MEDIUM ISSUES (Medium Priority)

### 16. **No Position Lock During Order Execution**
- Two concurrent trading cycles could try to buy the same stock simultaneously
- First cycle buys, second cycle sees existing position and skips
- But they might both fetch prices and generate signals in parallel
- Race condition in `_place_buy_order()` line 185-189

### 17. **Consensus Signal for SELL Has Redundant Check**
**File:** `engine.py:150`
- Line 142: Filters signals to `confidence >= 0.45`
- Line 150: Checks `buy_confidence >= 0.45` again
- Redundant but harmless

### 18. **Correlation Check Doesn't Account for Position Size**
- Checks only the number of correlated stocks, not the exposure
- Could hold 2 IT stocks but 50% of portfolio in IT

### 19. **No Maximum Daily Trades Limit**
- Could place many trades in a row
- No circuit breaker on trade frequency (only position count)

### 20. **ATR Calculation Uses Pandas Rolling Mean**
- Inefficient for large dataframes
- Not optimized for performance

---

## 📊 SUMMARY

| Severity | Count | Items |
|----------|-------|-------|
| 🔴 Critical | 9 | Trading hours, missing entries, Kelly bug, P&L calc, broker failure, ML file, learner bug, correlation, stale prices |
| 🟡 Major | 6 | Consensus signals, feature leakage, position entry, equity peak, gap handling, DB locks |
| 🟠 Medium | 5 | Race conditions, redundant checks, correlation exposure, trade limits, ATR calc |

---

## ✅ RECOMMENDATIONS (Priority Order)

1. **FIX IMMEDIATELY:**
   - [ ] Update `TRADING_HOURS_END = 10` (Issue #1)
   - [ ] Create BUY trade records (Issue #2)
   - [ ] Fix learner.py scaler bug (Issue #7)
   - [ ] Fix Kelly trade count bug (Issue #3)

2. **FIX WITHIN 24 HOURS:**
   - [ ] Fix correlation check with .NS suffix (Issue #8)
   - [ ] Fix broker failure DB corruption (Issue #5)
   - [ ] Fix P&L slippage calculation (Issue #4)
   - [ ] Fix ML model file handling (Issue #6)

3. **REFACTOR SOON:**
   - [ ] Add overnight position close logic (Issue #14)
   - [ ] Improve P&L tracking with proper entry records (Issue #12)
   - [ ] Add race condition locking (Issue #16)

4. **MONITOR/TEST:**
   - [ ] Test with real NSE data to verify fixes
   - [ ] Backtest after each fix
   - [ ] Monitor equity curve daily

---

## 💡 GENERAL RECOMMENDATIONS

1. **Add integration tests** that verify:
   - Trade entry → Trade exit relationship
   - P&L matches cash change
   - Database consistency after each cycle

2. **Add reconciliation script** that:
   - Compares database positions vs broker account
   - Calculates actual P&L vs database P&L
   - Alerts on mismatches

3. **Add monitoring** for:
   - Stale prices
   - Failed orders
   - ML model performance drift
   - Daily P&L vs expected

4. **Documentation** needed for:
   - Risk limits and assumptions
   - Data sources and fallbacks
   - Feature engineering choices
   - Trading hours configuration

---

**Status:** Issues identified and ready for fixes.
**Estimated Fix Time:** 4-6 hours for critical issues, 8-12 hours for all issues.
