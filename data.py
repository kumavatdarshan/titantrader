import logging
import os
import random
import asyncio
import time
import tempfile
from datetime import datetime, timedelta, date as date_type

import pandas as pd

from config import Config

logger = logging.getLogger(__name__)

# True when running inside GitHub Actions — use server=True for NseIndiaApi
ON_GITHUB_ACTIONS = os.environ.get("GITHUB_ACTIONS") == "true"

# ─── Indian NSE symbols ──────────────────────────────────────────────────────
INDIAN_SYMBOLS = {
    'TCS', 'INFY', 'RELIANCE', 'HDFC', 'BAJAJFINSV', 'MARUTI',
    'SUNPHARMA', 'WIPRO', 'HCLTECH', 'TECHM', 'HDFCBANK', 'ICICIBANK',
    'SBIN', 'KOTAKBANK', 'AXISBANK', 'NIFTY50',
}

# Fallback mock prices (last resort only)
MOCK_PRICES = {
    "AAPL": 210, "TSLA": 245, "NVDA": 145, "SPY": 545,
    "MSFT": 430, "AMZN": 185, "GOOGL": 175, "META": 520,
    # Indian NSE stocks — both bare and .NS forms
    "TCS": 4100,        "TCS.NS": 4100,
    "INFY": 1750,       "INFY.NS": 1750,
    "RELIANCE": 2900,   "RELIANCE.NS": 2900,
    "HDFC": 2800,       "HDFC.NS": 2800,
    "HDFCBANK": 1680,   "HDFCBANK.NS": 1680,
    "BAJAJFINSV": 1520, "BAJAJFINSV.NS": 1520,
    "MARUTI": 12500,    "MARUTI.NS": 12500,
    "SUNPHARMA": 850,   "SUNPHARMA.NS": 850,
    "WIPRO": 480,       "WIPRO.NS": 480,
    "HCLTECH": 1850,    "HCLTECH.NS": 1850,
    "TECHM": 4200,      "TECHM.NS": 4200,
    "ICICIBANK": 1200,  "ICICIBANK.NS": 1200,
    "SBIN": 820,        "SBIN.NS": 820,
    "KOTAKBANK": 1750,  "KOTAKBANK.NS": 1750,
    "AXISBANK": 1180,   "AXISBANK.NS": 1180,
    "NIFTY50": 24000,
}

_failed_symbols: dict = {}


def _bare_symbol(symbol: str) -> str:
    """Strip .NS suffix if present: 'TCS.NS' -> 'TCS'."""
    return symbol[:-3] if symbol.endswith(".NS") else symbol


def _is_indian(symbol: str) -> bool:
    return _bare_symbol(symbol) in INDIAN_SYMBOLS or symbol.endswith(".NS")


# ─── NseIndiaApi helpers ─────────────────────────────────────────────────────

def _nse_live_price(symbol: str) -> dict | None:
    """Fetch real-time NSE price via NseIndiaApi."""
    try:
        from nse import NSE
        tmp = tempfile.gettempdir()
        nse = NSE(download_folder=tmp, server=ON_GITHUB_ACTIONS)
        bare = _bare_symbol(symbol)
        quote = nse.equityQuote(bare)
        nse.exit()

        if not quote:
            return None

        return {
            "price": float(quote.get("close", 0)),
            "timestamp": datetime.utcnow(),
            "source": "nse_live",
            "is_stale": False,
            "volume": int(quote.get("volume", 0)),
        }
    except Exception as e:
        logger.debug(f"NSE live price failed for {symbol}: {e}")
        return None


def _nse_historical(symbol: str, days: int) -> pd.DataFrame | None:
    """Fetch historical daily OHLCV from NSE via NseIndiaApi."""
    try:
        from nse import NSE
        tmp = tempfile.gettempdir()
        nse = NSE(download_folder=tmp, server=ON_GITHUB_ACTIONS)
        bare = _bare_symbol(symbol)
        to_dt = date_type.today()
        from_dt = to_dt - timedelta(days=days)

        data = nse.fetch_equity_historical_data(
            symbol=bare,
            series="EQ",
            from_date=from_dt,
            to_date=to_dt
        )
        nse.exit()

        if not data:
            return None

        rows = []
        for bar in data:
            rows.append({
                "Date": pd.to_datetime(bar.get("mtimestamp", "")),
                "Open": float(bar.get("chOpeningPrice", 0)),
                "High": float(bar.get("chTradeHighPrice", 0)),
                "Low": float(bar.get("chTradeLowPrice", 0)),
                "Close": float(bar.get("chClosingPrice", 0)),
                "Volume": int(bar.get("chTotTradedQty", 0)),
            })

        if not rows:
            return None

        df = pd.DataFrame(rows)
        df = df.sort_values("Date").reset_index(drop=True)
        df = df.dropna(subset=["Close"])
        return df if not df.empty else None

    except Exception as e:
        logger.warning(f"NSE historical failed for {symbol}: {e}")
        return None


def _synthetic_ohlcv(symbol: str, periods: int = 252) -> pd.DataFrame:
    """Generate realistic synthetic OHLCV with trend phases."""
    base_price = MOCK_PRICES.get(symbol, MOCK_PRICES.get(_bare_symbol(symbol), 1000))
    dates = pd.bdate_range(end=datetime.utcnow(), periods=periods)

    rows = []
    price = float(base_price)
    trend = random.choice([-1, 1])
    trend_days = 0

    for dt in dates:
        trend_days += 1
        if trend_days > random.randint(20, 40):
            trend = -trend
            trend_days = 0

        drift = trend * random.uniform(0.0005, 0.003)
        noise = random.gauss(0, 0.012)
        daily_ret = drift + noise

        open_p = price * (1 + random.uniform(-0.005, 0.005))
        close_p = price * (1 + daily_ret)
        high_p = max(open_p, close_p) * (1 + random.uniform(0, 0.008))
        low_p = min(open_p, close_p) * (1 - random.uniform(0, 0.008))

        rows.append({
            "Date": dt,
            "Open": round(open_p, 2),
            "High": round(high_p, 2),
            "Low": round(low_p, 2),
            "Close": round(close_p, 2),
            "Volume": random.randint(500_000, 20_000_000),
        })
        price = close_p

    return pd.DataFrame(rows)


def _get_mock_price(symbol: str) -> dict:
    """Return a mock price with ±1% noise."""
    key = symbol if symbol in MOCK_PRICES else _bare_symbol(symbol)
    if key not in MOCK_PRICES:
        raise ValueError(f"Symbol {symbol} not in mock data")
    base = MOCK_PRICES[key]
    price = base * (1 + random.uniform(-0.01, 0.01))
    return {
        "price": price,
        "timestamp": datetime.utcnow(),
        "source": "mock",
        "is_stale": False,
        "volume": random.randint(1_000_000, 10_000_000),
    }


# ─── Public API ────────────────────────────────────────────────────────────

async def fetch_price(symbol: str, use_mock: bool = True) -> dict:
    """
    Fetch current price for a symbol.

    For Indian NSE stocks:
        1. NseIndiaApi live (works on GitHub Actions with server=True)
        2. NseIndiaApi last close (fallback if live fails)
        3. mock fallback

    For non-Indian stocks:
        1. mock fallback
    """
    # Cooldown check — avoid hammering a failing source
    if symbol in _failed_symbols:
        fail_time, fail_count = _failed_symbols[symbol]
        if time.time() - fail_time < 300:
            logger.debug(f"{symbol}: In cooldown, using mock")
            return _get_mock_price(symbol)

    if _is_indian(symbol):
        # Try live price first
        result = await asyncio.get_event_loop().run_in_executor(
            None, _nse_live_price, symbol
        )
        if result:
            _failed_symbols.pop(symbol, None)
            logger.info(f"{symbol}: {result['price']:.2f} (source: nse_live)")
            return result

        # Market closed — use latest close from historical
        logger.debug(f"{symbol}: Live unavailable, fetching last close...")
        df = await asyncio.get_event_loop().run_in_executor(
            None, _nse_historical, symbol, 7
        )
        if df is not None and not df.empty:
            _failed_symbols.pop(symbol, None)
            last_close = float(df["Close"].iloc[-1])
            logger.info(f"{symbol}: {last_close:.2f} (source: nse_last_close)")
            return {
                "price": last_close,
                "timestamp": datetime.utcnow(),
                "source": "nse_last_close",
                "is_stale": True,
                "volume": int(df["Volume"].iloc[-1]),
            }

    else:
        # Non-Indian: use mock
        if symbol in MOCK_PRICES:
            _failed_symbols.pop(symbol, None)
            result = _get_mock_price(symbol)
            logger.info(f"{symbol}: {result['price']:.2f} (source: mock)")
            return result

    # All sources failed — use mock
    _failed_symbols[symbol] = (time.time(), _failed_symbols.get(symbol, (0, 0))[1] + 1)
    if use_mock:
        logger.warning(f"{symbol}: All sources failed — using mock")
        return _get_mock_price(symbol)
    raise RuntimeError(f"Could not fetch price for {symbol}")


async def fetch_ohlcv_candles(symbol: str, period: str = "1mo") -> dict:
    """
    Fetch historical OHLCV candles.

    For Indian NSE stocks:
        1. NseIndiaApi historical (works on GitHub Actions with server=True)
        2. synthetic mock (last resort)

    For non-Indian stocks:
        1. synthetic mock

    period: '1mo' | '3mo' | '6mo' | '1y' | '2y'
    Returns: {symbol, data: DataFrame, rows, source, success, error?}
    """
    period_to_days = {
        "1mo": 30, "3mo": 90, "6mo": 180, "1y": 365, "2y": 730,
    }
    days = period_to_days.get(period, 365)

    try:
        if _is_indian(symbol):
            logger.info(f"{symbol}: Fetching {days}d of NSE historical...")
            df = await asyncio.get_event_loop().run_in_executor(
                None, _nse_historical, symbol, days
            )
            if df is not None and not df.empty:
                logger.info(f"{symbol}: Got {len(df)} bars from NseIndiaApi")
                return {"symbol": symbol, "data": df, "rows": len(df),
                        "source": "nse", "success": True}

            logger.warning(f"{symbol}: NseIndiaApi returned no data — using synthetic")

        else:
            # Non-Indian: go straight to synthetic
            logger.info(f"{symbol}: Non-Indian symbol — using synthetic data")

        # Last resort: synthetic data
        if symbol not in MOCK_PRICES and _bare_symbol(symbol) not in MOCK_PRICES:
            return {"symbol": symbol, "data": None, "rows": 0,
                    "source": "none", "success": False,
                    "error": f"No data available for {symbol}"}

        df = _synthetic_ohlcv(symbol, periods=max(days, 252))
        logger.info(f"{symbol}: Generated {len(df)} synthetic bars")
        return {"symbol": symbol, "data": df, "rows": len(df),
                "source": "synthetic_mock", "success": True}

    except Exception as e:
        logger.error(f"Fatal error in fetch_ohlcv_candles for {symbol}: {e}")
        return {"symbol": symbol, "data": None, "rows": 0,
                "source": "none", "success": False, "error": str(e)}
