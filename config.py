import os
from dotenv import load_dotenv
from datetime import time

load_dotenv()


class Config:
    TRADING_MODE = os.getenv("TRADING_MODE", "local_paper")
    STARTING_CAPITAL = float(os.getenv("STARTING_CAPITAL", 10000))
    SYMBOLS = os.getenv("SYMBOLS", "AAPL,MSFT,NVDA,GOOGL,TSLA,SPY,JPM,XOM,QQQ").split(",")
    TRADE_INTERVAL_MINUTES = int(os.getenv("TRADE_INTERVAL_MINUTES", 5))

    MARKET_OPEN_UTC = os.getenv("MARKET_OPEN_UTC", "13:30")
    MARKET_CLOSE_UTC = os.getenv("MARKET_CLOSE_UTC", "20:00")

    MAX_POSITION_PCT = float(os.getenv("MAX_POSITION_PCT", 0.10))
    STOP_LOSS_PCT = float(os.getenv("STOP_LOSS_PCT", 0.03))
    TAKE_PROFIT_PCT = float(os.getenv("TAKE_PROFIT_PCT", 0.06))
    MAX_OPEN_POSITIONS = int(os.getenv("MAX_OPEN_POSITIONS", 9))
    DRAWDOWN_PAUSE_PCT = float(os.getenv("DRAWDOWN_PAUSE_PCT", 0.12))

    KELLY_FRACTION_CAP = float(os.getenv("KELLY_FRACTION_CAP", 0.25))
    MIN_KELLY_TRADES = int(os.getenv("MIN_KELLY_TRADES", 10))

    FEE_RATE = float(os.getenv("FEE_RATE", 0.001))
    SLIPPAGE_BPS = int(os.getenv("SLIPPAGE_BPS", 5))

    ALPACA_API_KEY = os.getenv("ALPACA_API_KEY", "")
    ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "")
    ALPACA_PAPER_URL = os.getenv("ALPACA_PAPER_URL", "https://paper-api.alpaca.markets")
    ALPACA_LIVE_URL = os.getenv("ALPACA_LIVE_URL", "https://api.alpaca.markets")

    DASHBOARD_PORT = int(os.getenv("DASHBOARD_PORT", 8000))
    DASHBOARD_REFRESH_SECONDS = int(os.getenv("DASHBOARD_REFRESH_SECONDS", 30))

    ML_MIN_ACCURACY = float(os.getenv("ML_MIN_ACCURACY", 0.60))
    ML_MIN_TRADES_TO_TRAIN = int(os.getenv("ML_MIN_TRADES_TO_TRAIN", 30))
    ML_RETRAIN_HOUR = int(os.getenv("ML_RETRAIN_HOUR", 20))

    LOG_LEVEL = os.getenv("LOG_LEVEL", "DEBUG")

    DB_PATH = "titantrader.db"

    @classmethod
    def is_live_mode(cls):
        return cls.TRADING_MODE in ("alpaca_live",)

    @classmethod
    def is_paper_mode(cls):
        return cls.TRADING_MODE in ("local_paper", "alpaca_paper")
