import logging
from datetime import datetime, timedelta
import random
import asyncio
import time
import pandas as pd
from config import Config

logger = logging.getLogger(__name__)

# User agents to rotate and avoid blocks
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36',
    'Mozilla/5.0 (iPhone; CPU iPhone OS 14_6 like Mac OS X)',
]

MOCK_PRICES = {
    "BTC-USD": 67000,
    "ETH-USD": 3400,
    "AAPL": 210,
    "TSLA": 245,
    "NVDA": 145,
    "SPY": 545,
    "MSFT": 430,
    "AMZN": 185,
    "GOOGL": 175,
    "META": 520,
    # Indian NSE stocks (with and without .NS suffix)
    "TCS": 4100,
    "TCS.NS": 4100,
    "INFY": 1750,
    "INFY.NS": 1750,
    "RELIANCE": 2900,
    "RELIANCE.NS": 2900,
    "HDFC": 2800,
    "HDFC.NS": 2800,
    "HDFCBANK": 1680,
    "HDFCBANK.NS": 1680,
    "BAJAJFINSV": 1520,
    "BAJAJFINSV.NS": 1520,
    "MARUTI": 12500,
    "MARUTI.NS": 12500,
    "SUNPHARMA": 850,
    "SUNPHARMA.NS": 850,
    "WIPRO": 480,
    "WIPRO.NS": 480,
    "HCLTECH": 1850,
    "HCLTECH.NS": 1850,
    "TECHM": 4200,
    "TECHM.NS": 4200,
    "ICICIBANK": 1200,
    "ICICIBANK.NS": 1200,
    "SBIN": 820,
    "SBIN.NS": 820,
    "KOTAKBANK": 1750,
    "KOTAKBANK.NS": 1750,
    "AXISBANK": 1180,
    "AXISBANK.NS": 1180,
    "NIFTY50": 24000,
}

# Cache for recently failed symbols (avoid retrying too quickly)
_failed_symbols = {}


async def fetch_price(symbol: str, use_mock: bool = True) -> dict:
    """
    Fetch price with robust error handling and retries.
    Fallback chain: yfinance → mock data → error
    """
    try:
        import yfinance as yf

        # Check if recently failed
        if symbol in _failed_symbols:
            fail_time, fail_count = _failed_symbols[symbol]
            if time.time() - fail_time < 300:  # 5 min cooldown
                logger.debug(f"{symbol}: In cooldown ({fail_count} failures), using mock data")
                return _get_mock_price(symbol)

        # Determine yfinance symbol
        indian_symbols = {'TCS', 'INFY', 'RELIANCE', 'HDFC', 'BAJAJFINSV', 'MARUTI', 'SUNPHARMA', 'WIPRO', 'HCLTECH', 'TECHM', 'HDFCBANK', 'ICICIBANK', 'SBIN', 'KOTAKBANK', 'AXISBANK', 'NIFTY50'}
        yf_symbol = symbol if symbol.endswith(".NS") else (symbol + ".NS" if symbol in indian_symbols else symbol)

        logger.debug(f"Fetching {yf_symbol} from yfinance...")

        # Retry logic with exponential backoff
        max_retries = 3
        for attempt in range(max_retries):
            try:
                # Set random user-agent
                session = None
                try:
                    import requests
                    session = requests.Session()
                    session.headers['User-Agent'] = random.choice(USER_AGENTS)
                except:
                    pass

                # Download with timeout
                data = yf.download(
                    yf_symbol,
                    period="5d",
                    progress=False,
                    timeout=10,
                    session=session
                )

                if data.empty:
                    raise Exception(f"Empty data returned from yfinance")

                latest = data.iloc[-1]
                price = float(latest['Close'])
                timestamp = data.index[-1].to_pydatetime()

                # Check if data is stale
                now = datetime.utcnow()
                age_minutes = (now - timestamp).total_seconds() / 60
                is_stale = age_minutes > 30  # 30 min stale threshold

                # Clear failed cache on success
                if symbol in _failed_symbols:
                    del _failed_symbols[symbol]

                logger.info(f"{symbol}: {price:.2f} (age: {age_minutes:.0f}m, source: yfinance)")

                return {
                    'price': price,
                    'timestamp': timestamp,
                    'source': 'yfinance',
                    'is_stale': is_stale,
                    'volume': int(latest.get('Volume', 0))
                }

            except Exception as e:
                error_msg = str(e)

                # Detect specific errors
                if '404' in error_msg or 'not found' in error_msg.lower():
                    logger.error(f"{symbol}: Not found on yfinance (404)")
                    break  # Don't retry, symbol doesn't exist

                elif 'connection' in error_msg.lower() or 'timeout' in error_msg.lower():
                    logger.warning(f"{symbol}: Network error (attempt {attempt+1}/{max_retries}): {error_msg}")
                    if attempt < max_retries - 1:
                        wait = (2 ** attempt) + random.uniform(0, 1)  # Exponential backoff with jitter
                        logger.warning(f"Retrying in {wait:.1f}s...")
                        await asyncio.sleep(wait)
                    continue

                else:
                    logger.warning(f"{symbol}: Error (attempt {attempt+1}/{max_retries}): {error_msg}")
                    if attempt < max_retries - 1:
                        wait = (2 ** attempt) + random.uniform(0, 1)
                        await asyncio.sleep(wait)
                    continue

        # All retries failed
        logger.warning(f"{symbol}: yfinance failed after {max_retries} attempts")
        _failed_symbols[symbol] = (time.time(), _failed_symbols.get(symbol, (0, 0))[1] + 1)

        # Fallback to mock
        if use_mock:
            logger.info(f"{symbol}: Using mock data (fallback)")
            return _get_mock_price(symbol)
        else:
            raise Exception(f"Failed to fetch {symbol} and mock disabled")

    except Exception as e:
        logger.error(f"Fatal error fetching {symbol}: {e}")
        if use_mock:
            return _get_mock_price(symbol)
        raise


def _get_mock_price(symbol: str) -> dict:
    """Get mock price for a symbol."""
    if symbol not in MOCK_PRICES:
        raise ValueError(f"Symbol {symbol} not in mock data")

    base_price = MOCK_PRICES[symbol]
    noise = random.uniform(-0.01, 0.01)  # 1% random variation
    price = base_price * (1 + noise)

    return {
        'price': price,
        'timestamp': datetime.utcnow(),
        'source': 'mock',
        'is_stale': False,
        'volume': random.randint(1000000, 10000000)
    }


async def fetch_ohlcv_candles(symbol: str, period: str = "1mo") -> dict:
    """
    Fetch OHLCV candles with robust fallback chain.
    Alpaca → yfinance → synthetic mock data
    """
    try:
        import yfinance as yf

        # Try Alpaca first if configured
        if Config.TRADING_MODE.startswith("alpaca") and Config.ALPACA_API_KEY:
            try:
                logger.debug(f"Fetching {symbol} from Alpaca...")
                from alpaca_trade_api.rest import REST

                base_url = Config.ALPACA_PAPER_URL if Config.TRADING_MODE == "alpaca_paper" else Config.ALPACA_LIVE_URL
                api = REST(
                    key_id=Config.ALPACA_API_KEY,
                    secret_key=Config.ALPACA_SECRET_KEY,
                    base_url=base_url,
                    raw_data=True
                )

                # Convert period to timeframe and start date
                if period == "1mo":
                    timeframe = "1Day"
                    start = (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d")
                elif period == "3mo":
                    timeframe = "1Day"
                    start = (datetime.utcnow() - timedelta(days=90)).strftime("%Y-%m-%d")
                else:
                    timeframe = "1Day"
                    start = (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d")

                bars = api.get_bars(
                    symbol,
                    timeframe,
                    start=start,
                    limit=100,
                    adjustment='all'
                )

                if bars and len(bars) > 0:
                    data = []
                    bars_list = list(bars.values()) if isinstance(bars, dict) else list(bars)

                    for bar in bars_list:
                        data.append({
                            'Date': pd.Timestamp(bar.t) if hasattr(bar, 't') else pd.Timestamp(bar['t']),
                            'Open': float(bar.o if hasattr(bar, 'o') else bar['o']),
                            'High': float(bar.h if hasattr(bar, 'h') else bar['h']),
                            'Low': float(bar.l if hasattr(bar, 'l') else bar['l']),
                            'Close': float(bar.c if hasattr(bar, 'c') else bar['c']),
                            'Volume': float(bar.v if hasattr(bar, 'v') else bar['v'])
                        })

                    if data:
                        df = pd.DataFrame(data)
                        df = df.sort_values('Date').reset_index(drop=True)
                        logger.info(f"Fetched {len(df)} bars for {symbol} from Alpaca")
                        return {
                            'symbol': symbol,
                            'data': df,
                            'rows': len(df),
                            'source': 'alpaca',
                            'success': True
                        }

            except Exception as e:
                logger.warning(f"Alpaca fetch failed: {e}, falling back to yfinance...")

        # Fallback to yfinance with retry
        logger.debug(f"Fetching {symbol} from yfinance...")

        indian_symbols = {'TCS', 'INFY', 'RELIANCE', 'HDFC', 'BAJAJFINSV', 'MARUTI', 'SUNPHARMA', 'WIPRO', 'HCLTECH', 'TECHM', 'HDFCBANK', 'ICICIBANK', 'SBIN', 'KOTAKBANK', 'AXISBANK', 'NIFTY50'}
        yf_symbol = symbol if symbol.endswith(".NS") else (symbol + ".NS" if symbol in indian_symbols else symbol)

        max_retries = 3
        for attempt in range(max_retries):
            try:
                df = yf.download(yf_symbol, period=period, progress=False, timeout=10)

                if df.empty:
                    raise Exception("Empty data")

                df['Date'] = df.index
                df = df.reset_index(drop=True)

                logger.info(f"Fetched {len(df)} bars for {symbol} from yfinance")
                return {
                    'symbol': symbol,
                    'data': df,
                    'rows': len(df),
                    'source': 'yfinance',
                    'success': True
                }

            except Exception as e:
                logger.warning(f"yfinance attempt {attempt+1}/{max_retries} failed: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep((2 ** attempt) + random.uniform(0, 1))

        # Generate synthetic data as last resort
        logger.warning(f"All real data sources failed for {symbol}, using synthetic data")
        if symbol not in MOCK_PRICES:
            logger.error(f"Symbol {symbol} not in mock prices")
            return {
                'symbol': symbol,
                'data': None,
                'rows': 0,
                'source': 'none',
                'success': False,
                'error': f"Symbol {symbol} not available"
            }

        logger.info(f"Generating synthetic OHLCV for {symbol}")
        base_price = MOCK_PRICES[symbol]
        dates = pd.date_range(end=datetime.utcnow(), periods=100, freq='1D')

        data = []
        current_price = base_price
        for date in dates:
            daily_change = random.uniform(-0.03, 0.03)
            open_price = current_price * (1 - random.uniform(0, 0.01))
            high = current_price * (1 + abs(daily_change) + random.uniform(0, 0.02))
            low = current_price * (1 - abs(daily_change) - random.uniform(0, 0.02))
            close = current_price * (1 + daily_change)
            current_price = close

            data.append({
                'Date': date,
                'Open': open_price,
                'High': high,
                'Low': low,
                'Close': close,
                'Volume': random.randint(1000000, 50000000)
            })

        df = pd.DataFrame(data)
        logger.info(f"Generated {len(df)} synthetic bars for {symbol}")

        return {
            'symbol': symbol,
            'data': df,
            'rows': len(df),
            'source': 'synthetic_mock',
            'success': True
        }

    except Exception as e:
        logger.error(f"Fatal error in fetch_ohlcv_candles for {symbol}: {e}")
        return {
            'symbol': symbol,
            'data': None,
            'rows': 0,
            'source': 'none',
            'success': False,
            'error': str(e)
        }
