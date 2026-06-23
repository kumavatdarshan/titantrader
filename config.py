import os
from dotenv import load_dotenv
from datetime import time

load_dotenv()


class Config:
    # ===== Trading Mode & Account =====
    TRADING_MODE = os.getenv("TRADING_MODE", "alpaca_paper")
    STARTING_CAPITAL = float(os.getenv("STARTING_CAPITAL", 100000))
    DASHBOARD_PORT = int(os.getenv("DASHBOARD_PORT", 8000))
    TRADE_INTERVAL_MINUTES = int(os.getenv("TRADE_INTERVAL_MINUTES", 30))

    # ===== Universe: Indian NSE Stocks (Large Cap) =====
    SYMBOLS = os.getenv("SYMBOLS", "TCS.NS,INFY.NS,RELIANCE.NS,HDFC.NS,BAJAJFINSV.NS,MARUTI.NS,SUNPHARMA.NS,WIPRO.NS,HCLTECH.NS,TECHM.NS").split(",")

    # ===== Market Hours (UTC) - NSE (Indian Market) =====
    MARKET_OPEN_UTC = "03:45"  # 9:15 AM IST (NSE open)
    MARKET_CLOSE_UTC = "10:00"  # 3:30 PM IST (NSE close)
    MARKET_OPEN_HOUR_UTC = 3
    MARKET_CLOSE_HOUR_UTC = 10

    # ===== High Probability Trading Windows =====
    TRADING_HOURS_START = 4   # 9:30 AM IST (4 AM UTC)
    TRADING_HOURS_END = 10    # 3:30 PM IST (10 AM UTC) - full NSE market hours
    FIRST_HOUR_ONLY = False   # Option to only trade first hour for high volatility

    # ===== Risk Management (CRITICAL) =====
    RISK_PER_TRADE_PCT = 0.02  # Max 2% risk per trade (PROFESSIONAL STANDARD)
    MAX_OPEN_POSITIONS = 5     # Max 5 concurrent positions
    MAX_DAILY_LOSS_PCT = 0.10  # Stop trading if down 10% in a day (circuit breaker)
    MAX_POSITION_PCT = float(os.getenv("MAX_POSITION_PCT", 0.15))  # Max 15% of portfolio in one position

    # ===== ATR-Based Dynamic Stops =====
    USE_ATR_STOPS = True       # Use ATR for stops instead of fixed %
    ATR_PERIOD = 14
    ATR_STOP_MULTIPLIER = 2.0  # 2x ATR for stop-loss
    ATR_TARGET_MULTIPLIER = 3.0  # 3x ATR for take-profit

    # ===== Fallback Fixed Stops (if ATR unavailable) =====
    STOP_LOSS_PCT = 0.03       # 3% stop-loss
    TAKE_PROFIT_PCT = 0.06     # 6% take-profit

    # ===== Position Sizing =====
    KELLY_FRACTION_CAP = 0.25   # Use 25% Kelly (conservative)
    MIN_KELLY_TRADES = 30       # Need 30 trades for Kelly to be reliable
    BASE_KELLY_WIN_RATE = 0.55  # Assume 55% win rate (professional traders are 52-60%)
    BASE_KELLY_WIN_SIZE = 1.5   # Avg winner is 1.5x risk
    BASE_KELLY_LOSS_SIZE = 1.0  # Avg loser is 1x risk

    # ===== Market Regime Detection =====
    VOLATILITY_FILTER_ENABLED = True
    VIX_HIGH_THRESHOLD = 25     # Don't trade if VIX > 25 (market stress)

    # ===== Correlation Filter =====
    MAX_CORRELATION = 0.70      # Don't hold stocks with correlation > 0.7
    CORRELATION_LOOKBACK_DAYS = 30

    # ===== Costs =====
    FEE_RATE = 0.0              # Alpaca paper: no fees
    SLIPPAGE_BPS = 2            # Assume 2 bps slippage in execution

    # ===== Alpaca =====
    ALPACA_API_KEY = os.getenv("ALPACA_API_KEY", "")
    ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "")
    ALPACA_PAPER_URL = "https://paper-api.alpaca.markets"
    ALPACA_LIVE_URL = "https://api.alpaca.markets"

    # ===== ML Model =====
    ML_ENABLED = True
    ML_MIN_ACCURACY = 0.60      # Only deploy if >= 60% accuracy
    ML_MIN_TRADES_TO_TRAIN = 50 # Need 50 closed trades for training
    ML_RETRAIN_HOUR = 22        # Retrain at 10 PM UTC = 6 PM ET (after 4 PM close)
    ML_VALIDATION_SPLIT = 0.2   # 20% validation set

    # ===== Logging =====
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    DB_PATH = "titantrader.db"

    @classmethod
    def is_live_mode(cls):
        return cls.TRADING_MODE == "alpaca_live"

    @classmethod
    def is_paper_mode(cls):
        return cls.TRADING_MODE in ("alpaca_paper", "local_paper")
