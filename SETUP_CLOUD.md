# TitanTrader Cloud Setup (GitHub Actions)

**Setup Time: 5 minutes**
**Cost: $0 (free forever)**

## Step-by-Step

### 1. Go to GitHub Settings

```
https://github.com/kumavatdarshan/titantrader/settings/secrets/actions
```

### 2. Add 5 Secrets (New repository secret button)

Add these exactly:

| Name | Value |
|------|-------|
| `TRADING_MODE` | `alpaca_paper` |
| `ALPACA_API_KEY` | (from alpaca.markets) |
| `ALPACA_SECRET_KEY` | (from alpaca.markets) |
| `STARTING_CAPITAL` | `10000` |
| `SYMBOLS` | `AAPL,TSLA,NVDA,SPY,MSFT` |

### 3. Enable Actions

- Go to Actions tab
- If disabled, enable it

### 4. Done!

Bot will run automatically every 30 minutes.

## View Results

- **Logs**: Actions tab → latest run → output
- **Database**: Check GitHub repo → titantrader.db
- **Profits**: See in logs each cycle

## How to Know It's Working

Logs will show:
```
TRADING CYCLE START
[SYMBOL]: BUY signal
[SYMBOL]: Order filled
Equity: $10,245.67
TRADING CYCLE END
```

## Stop the Bot

- Go to Actions tab
- Disable the workflow

## Restart Bot

- Same as Enable Actions

## Scale to Real Money

When ready for real trading:
1. Change TRADING_MODE to `alpaca_live`
2. Use real Alpaca credentials
3. Increase STARTING_CAPITAL
4. Done! Bot trades real money

---

**That's it. Bot runs 24/7 on GitHub servers.**
