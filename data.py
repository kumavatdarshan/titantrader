import logging
from datetime import datetime, timedelta
import random
import asyncio
import yfinance as yf
import pandas as pd
from config import Config

logger = logging.getLogger(__name__)


def retry_on_timeout(max_retries=3, delay=1.0):
    """Decorator to retry async functions on timeout/connection errors."""
    def decorator(func):
        async def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except (TimeoutError, ConnectionError, Exception) as e:
                    if attempt < max_retries - 1:
                        wait_time = delay * (2 ** attempt)  # Exponential backoff
                        logger.warning(f"Attempt {attempt + 1}/{max_retries} failed for {func.__name__}: {e}. Retrying in {wait_time}s...")
                        await asyncio.sleep(wait_time)
                    else:
                        logger.error(f"All {max_retries} retries failed for {func.__name__}")
                        raise
        return wrapper
    return decorator

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
}


@retry_on_timeout(max_retries=2, delay=0.5)
async def fetch_price(symbol: str, use_mock: bool = True) -> dict:
    """Fetch price from yfinance with retry logic. Falls back to mock data if unavailable."""
    try:
        import yfinance as yf
        # Add user-agent to prevent blocking
        ticker = yf.Ticker(symbol, session=None)
        data = yf.download(symbol, period="5d", progress=False, timeout=5)

        if data.empty:
            raise Exception(f"No data for {symbol}")

        latest = data.iloc[-1]
        price = float(latest['Close'])
        timestamp = data.index[-1].to_pydatetime()

        now = datetime.utcnow()
        age_minutes = (now - timestamp).total_seconds() / 60
        is_stale = age_minutes > 10

        return {
            'price': price,
            'timestamp': timestamp,
            'source': 'yfinance',
            'is_stale': is_stale,
            'volume': int(latest.get('Volume', 0))
        }
    except Exception as e:
        if use_mock:
            logger.warning(f"Failed to fetch {symbol} from yfinance: {e}. Using mock data.")
            if symbol not in MOCK_PRICES:
                raise ValueError(f"Symbol {symbol} not in mock data and yfinance failed")

            base_price = MOCK_PRICES[symbol]
            noise = random.uniform(-0.005, 0.005)
            price = base_price * (1 + noise)

            return {
                'price': price,
                'timestamp': datetime.utcnow(),
                'source': 'mock',
                'is_stale': False,
                'volume': random.randint(1000000, 10000000)
            }
        else:
            logger.error(f"Failed to fetch {symbol} and mock disabled. Raising error.")
            raise


async def fetch_ohlcv_candles(symbol: str, period: str = "1mo") -> dict:
    """Fetch OHLCV candles from Alpaca (if available) or yfinance, with mock fallback."""

    # Try Alpaca first if in Alpaca mode
    if Config.TRADING_MODE.startswith("alpaca"):
        try:
            from alpaca_trade_api.rest import REST
            base_url = Config.ALPACA_PAPER_URL if Config.TRADING_MODE == "alpaca_paper" else Config.ALPACA_LIVE_URL
            api = REST(
                key_id=Config.ALPACA_API_KEY,
                secret_key=Config.ALPACA_SECRET_KEY,
                base_url=base_url
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

            # Get bars from Alpaca
            bars = api.get_bars(
                symbol,
                timeframe,
                start=start,
                limit=100,
                adjustment='all'
            )

            if bars is not None and len(bars) > 0:
                data = []

                if isinstance(bars, dict):
                    bars_list = list(bars.values())
                else:
                    bars_list = list(bars)

                for bar in bars_list:
                    data.append({
                        'Date': pd.Timestamp(bar.t) if hasattr(bar, 't') else pd.Timestamp(bar['t']),
                        'Open': float(bar.o if hasattr(bar, 'o') else bar['o']),
                        'High': float(bar.h if hasattr(bar, 'h') else bar['h']),
                        'Low': float(bar.l if hasattr(bar, 'l') else bar['l']),
                        'Close': float(bar.c if hasattr(bar, 'c') else bar['c']),
                        'Volume': float(bar.v if hasattr(bar, 'v') else bar['v'])
                    })

                if len(data) > 0:
                    df = pd.DataFrame(data)
                    df = df.sort_values('Date').reset_index(drop=True)
                    logger.info(f"✓ Fetched {len(df)} bars for {symbol} from Alpaca")

                    return {
                        'symbol': symbol,
                        'data': df,
                        'rows': len(df),
                        'source': 'alpaca',
                        'success': True
                    }

            raise Exception(f"No bars from Alpaca for {symbol}")

        except Exception as e:
            logger.warning(f"Failed to fetch {symbol} from Alpaca: {e}. Falling back to yfinance...")

    # Fallback to yfinance
    try:
        df = yf.download(symbol, period=period, progress=False, timeout=5)

        if df.empty:
            logger.error(f"No OHLCV data for {symbol}")
            raise Exception(f"No data for {symbol}")

        df['Date'] = df.index
        df = df.reset_index(drop=True)

        return {
            'symbol': symbol,
            'data': df,
            'rows': len(df),
            'source': 'yfinance',
            'success': True
        }
    except Exception as e:
        logger.warning(f"Failed to fetch OHLCV for {symbol} from yfinance: {e}")

        # Last resort: synthetic data for testing
        try:
            logger.info(f"Generating synthetic OHLCV data for {symbol} (paper testing)")
            if symbol not in MOCK_PRICES:
                return {
                    'symbol': symbol,
                    'data': None,
                    'rows': 0,
                    'source': 'none',
                    'success': False,
                    'error': str(e)
                }

            base_price = MOCK_PRICES[symbol]
            dates = pd.date_range(end=datetime.utcnow(), periods=100, freq='1D')

            data = []
            current_price = base_price
            for date in dates:
                daily_change = random.uniform(-0.02, 0.02)
                open_price = current_price * (1 - random.uniform(0, 0.005))
                high = current_price * (1 + abs(daily_change) + random.uniform(0, 0.01))
                low = current_price * (1 - abs(daily_change) - random.uniform(0, 0.01))
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

            return {
                'symbol': symbol,
                'data': df,
                'rows': len(df),
                'source': 'mock_synthetic',
                'success': True
            }
        except Exception as mock_e:
            logger.error(f"Failed to generate synthetic OHLCV for {symbol}: {mock_e}")
            return {
                'symbol': symbol,
                'data': None,
                'rows': 0,
                'source': 'none',
                'success': False,
                'error': str(e)
            }
