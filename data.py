import logging
import os
import random
import asyncio
import time
from datetime import datetime, timedelta, date as date_type

import pandas as pd

from config import Config

logger = logging.getLogger(__name__)

# ─── Indian NSE symbols (without .NS suffix) ─────────────────────────────────
INDIAN_SYMBOLS = {
    'TCS', 'INFY', 'RELIANCE', 'HDFC', 'BAJAJFINSV', 'MARUTI',
    'SUNPHARMA', 'WIPRO', 'HCLTECH', 'TECHM', 'HDFCBANK', 'ICICIBANK',
    'SBIN', 'KOTAKBANK', 'AXISBANK', 'NIFTY50',
}

# ─── Fallback mock prices (last resort only) ─────────────────────────────────
MOCK_PRICES = {
    # US stocks
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

# In-memory cooldown cache: symbol -> (fail_timestamp, fail_count)
_failed_symbols: dict = {}


def _bare_symbol(symbol: str) -> str:
    """Strip .NS suffix if present: 'TCS.NS' -> 'TCS'."""
    return symbol[:-3] if symbol.endswith(".NS") else symbol


def _is_indian(symbol: str) -> bool:
    return _bare_symbol(symbol) in INDIAN_SYMBOLS or symbol.endswith(".NS")


def _ensure_jugaad_cache() -> None:
    """
    jugaad-data has a Windows bug where it crashes if its cache dirs
    don't already exist. Pre-create them so it never fails on startup.
    """
    local = os.path.join(os.path.expanduser("~"), "AppData", "Local")
    for folder in ("nsehistory-stock", "nselive"):
        path = os.path.join(local, folder, folder, "Cache")
        os.makedirs(path, exist_ok=True)


# ─── jugaad-data helpers ─────────────────────────────────────────────────────

def _jugaad_live_price(symbol: str) -> dict | None:
    """
    Fetch real-time NSE price via jugaad-data NSELive.
    Returns None if market is closed or request fails.
    """
    try:
        _ensure_jugaad_cache()
        from jugaad_data.nse import NSELive
        n = NSELive()
        bare = _bare_symbol(symbol)
        q = n.stock_quote(bare)
        price_info = q.get("priceInfo", {})
        last_price = price_info.get("lastPrice")
        if last_price is None:
            return None
        return {
            "price": float(last_price),
            "timestamp": datetime.utcnow(),
            "source": "jugaad_live",
            "is_stale": False,
            "volume": int(price_info.get("totalTradedVolume", 0) or 0),
        }
    except Exception as e:
        logger.debug(f"jugaad live price failed for {symbol}: {e}")
        return None


def _jugaad_historical(symbol: str, days: int) -> pd.DataFrame | None:
    """
    Fetch historical daily OHLCV from NSE via jugaad-data.
    Returns a DataFrame with columns: Date, Open, High, Low, Close, Volume
    or None on failure.
    """
    try:
        _ensure_jugaad_cache()
        from jugaad_data.nse import stock_df
        bare = _bare_symbol(symbol)
        to_dt = date_type.today()
        from_dt = to_dt - timedelta(days=days)
        df = stock_df(symbol=bare, from_date=from_dt, to_date=to_dt, series="EQ")
        if df is None or df.empty:
            return None
        # Rename jugaad columns to our standard names
        df = df.rename(columns={
            "DATE": "Date",
            "OPEN": "Open",
            "HIGH": "High",
            "LOW": "Low",
            "CLOSE": "Close",
            "VOLUME": "Volume",
        })
        # Keep only what we need
        df = df[["Date", "Open", "High", "Low", "Close", "Volume"]].copy()
        df["Date"] = pd.to_datetime(df["Date"])
        df = df.sort_values("Date").reset_index(drop=True)
        # Cast numeric columns
        for col in ("Open", "High", "Low", "Close", "Volume"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna(subset=["Close"])
        return df if not df.empty else None
    except Exception as e:
        logger.warning(f"jugaad historical failed for {symbol}: {e}")
        return None



def _synthetic_ohlcv(symbol: str, periods: int = 252) -> pd.DataFrame:
    """
    Generate realistic synthetic OHLCV data as absolute last resort.
    Uses a random walk with trend phases so strategies can find signals.
    """
    base_price = MOCK_PRICES.get(symbol, MOCK_PRICES.get(_bare_symbol(symbol), 1000))
    dates = pd.bdate_range(end=datetime.utcnow(), periods=periods)

    rows = []
    price = float(base_price)
    trend = random.choice([-1, 1])
    trend_days = 0

    for dt in dates:
        # Switch trend direction every 20-40 days
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


# ─── Public API ───────────────────────────────────────────────────────────────

async def fetch_price(symbol: str, use_mock: bool = True) -> dict:
    """
    Fetch current price for a symbol.

    For Indian NSE stocks:
        1. jugaad-data NSELive  (real-time, works only when market is open)
        2. jugaad-data last close (most recent historical bar)
        3. mock fallback

    For non-Indian stocks:
        1. mock fallback (jugaad-data covers NSE only)
    """
    # Cooldown check — avoid hammering a failing source
    if symbol in _failed_symbols:
        fail_time, fail_count = _failed_symbols[symbol]
        if time.time() - fail_time < 300:
            logger.debug(f"{symbol}: In cooldown, using mock")
            return _get_mock_price(symbol)

    if _is_indian(symbol):
        # Try live price first (only works during market hours)
        result = await asyncio.get_event_loop().run_in_executor(
            None, _jugaad_live_price, symbol
        )
        if result:
            _failed_symbols.pop(symbol, None)
            logger.info(f"{symbol}: {result['price']:.2f} (source: jugaad_live)")
            return result

        # Market closed — use latest close from historical
        logger.debug(f"{symbol}: Live price unavailable, fetching last close...")
        df = await asyncio.get_event_loop().run_in_executor(
            None, _jugaad_historical, symbol, 7
        )
        if df is not None and not df.empty:
            _failed_symbols.pop(symbol, None)
            last_close = float(df["Close"].iloc[-1])
            logger.info(f"{symbol}: {last_close:.2f} (source: jugaad_last_close)")
            return {
                "price": last_close,
                "timestamp": datetime.utcnow(),
                "source": "jugaad_last_close",
                "is_stale": True,
                "volume": int(df["Volume"].iloc[-1]),
            }

    else:
        # Non-Indian: use mock price (jugaad-data only covers NSE)
        if symbol in MOCK_PRICES:
            _failed_symbols.pop(symbol, None)
            result = _get_mock_price(symbol)
            logger.info(f"{symbol}: {result['price']:.2f} (source: mock)")
            return result

    # All sources failed — use mock
    _failed_symbols[symbol] = (time.time(), _failed_symbols.get(symbol, (0, 0))[1] + 1)
    if use_mock:
        logger.warning(f"{symbol}: All sources failed — using mock price")
        return _get_mock_price(symbol)
    raise RuntimeError(f"Could not fetch price for {symbol}")


async def fetch_ohlcv_candles(symbol: str, period: str = "1mo") -> dict:
    """
    Fetch historical OHLCV candles.

    For Indian NSE stocks:
        1. jugaad-data historical  (real NSE data)
        2. synthetic mock          (last resort)

    For non-Indian stocks:
        1. synthetic mock (jugaad-data covers NSE only)

    period: '1mo' | '3mo' | '6mo' | '1y' | '2y'
    Returns: {symbol, data: DataFrame, rows, source, success, error?}
    """
    period_to_days = {
        "1mo": 30, "3mo": 90, "6mo": 180, "1y": 365, "2y": 730,
    }
    days = period_to_days.get(period, 365)

    try:
        if _is_indian(symbol):
            logger.info(f"{symbol}: Fetching {days}d of NSE historical data...")
            df = await asyncio.get_event_loop().run_in_executor(
                None, _jugaad_historical, symbol, days
            )
            if df is not None and not df.empty:
                logger.info(f"{symbol}: Got {len(df)} bars from jugaad-data")
                return {"symbol": symbol, "data": df, "rows": len(df),
                        "source": "jugaad", "success": True}

            logger.warning(f"{symbol}: jugaad-data returned no data — using synthetic")

        else:
            # Non-Indian symbol: go straight to synthetic (jugaad-data covers NSE only)
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
