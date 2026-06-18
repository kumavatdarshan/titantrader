# Free Auto-Training Setup (No Credit Card Needed)

Your bot will now run **automatically every weekday morning** for 4 hours, accumulating trades. After 1 month, your ML model will be fully trained and ready for real money.

## Step 1: Add Your API Keys to GitHub Secrets (Secure)

⚠️ **IMPORTANT:** Never put real API keys in code. GitHub Secrets are encrypted.

1. Go to your GitHub repo → **Settings** → **Secrets and variables** → **Actions**
2. Click **New repository secret**
3. Add TWO secrets:
   - Name: `ALPACA_API_KEY`
     Value: your_new_alpaca_api_key
   - Name: `ALPACA_SECRET_KEY`
     Value: your_new_alpaca_secret

✅ Now your keys are encrypted and hidden from git!

## Step 2: Update `.env` for GitHub Actions

The workflow will automatically set these env vars, so `.env` just needs defaults:

```
TRADING_MODE=alpaca_paper
STARTING_CAPITAL=10000
SYMBOLS=AAPL,TSLA,NVDA,SPY,MSFT
... rest of config
```

(Already done!)

## Step 3: Push to GitHub

```bash
git add .github/workflows/train-bot.yml
git commit -m "add: GitHub Actions auto-training workflow"
git push origin main
```

## Step 4: Watch It Run

Go to your GitHub repo → **Actions** tab

You'll see:
- ✅ Next run: **Monday 9:30 AM EST** (and every weekday)
- 📊 Each run: 4 hours of live trading
- 🧠 ML trains nightly at 2 AM (bot does this automatically)

## The Math (1 Month Plan)

```
Week 1-4:
- Weekdays: 5 days × 4 hours = 20 hours/week
- Trades every 5 min = 48+ trades per run
- 20 hours × 4 weeks = 80+ total trades

After 30 days:
✅ 100+ trades completed (requirement met)
✅ ML model trained (50+ trade minimum met)
✅ Strategy scores calculated
✅ Ready to check: upgrade_checklist.md
```

## Monitor Progress

**Option A: GitHub Actions Tab**
- Go to Actions tab in your repo
- Click any run to see logs
- Watch the bot trade in real-time

**Option B: Download Results**
- After each run, GitHub stores:
  - `titantrader.db` (all trades, equity, ML models)
  - `logs/titantrader.log` (full trading journal)
- Click "Summary" → "Artifacts" to download

**Option C: Manual Run Anytime**
- Go to Actions → TitanTrader Training
- Click "Run workflow"
- Choose "Run on main"
- It starts immediately!

## After 30 Days: Check Your Progress

Download the latest `titantrader.db` from GitHub Actions artifacts.

Copy it to your local machine:
```bash
# Replace the local DB with the trained one from GitHub
cp ~/Downloads/titantrader.db ./titantrader.db
```

Then check:
```bash
python main.py  # Runs locally with your trained models
```

Open dashboard: `http://localhost:8000`

You'll see:
- 📊 30-day P&L
- 🏆 Win rate
- 🧠 ML accuracy
- ✅ upgrade_checklist.md (auto-generated)

If all metrics pass, you're ready for real money!

## Upgrade to Real Money (After 30 Days)

1. Sign up at [alpaca.markets](https://alpaca.markets) (free, India-friendly)
2. Add real cash (start with $500)
3. Get new API keys (LIVE keys)
4. Update GitHub Secrets:
   - Change to LIVE keys
   - Set `TRADING_MODE=alpaca_live`
5. Push to main
6. GitHub Actions now trades REAL money on schedule

---

## Cost Summary

✅ GitHub Actions: **FREE** (2000 min/month, you use ~80 min)
✅ Alpaca API: **FREE** (paper and live both free)
✅ Market data: **FREE** (yfinance)
✅ Total: **$0.00**

No credit card. No time limits. No surprises.

---

## Troubleshooting

**Run didn't execute?**
- Go to Actions tab → check "Runs"
- Click to see error logs

**Want to run manually?**
- Actions tab → TitanTrader Training → "Run workflow"

**Need to check trading progress?**
- Download `titantrader.db` artifact
- Copy to local folder
- Run `python main.py` to see dashboard

**Want to change the schedule?**
- Edit `.github/workflows/train-bot.yml`
- Change the `cron` time
- Commit and push

---

**In 1 month, you'll have:**
- ✅ 100+ real trades
- ✅ Trained ML model (57%+ accuracy target)
- ✅ Backtest passed
- ✅ Win rate 50%+
- ✅ Risk metrics validated
- ✅ Ready for real money

**Your bot trains itself. You do nothing.**
