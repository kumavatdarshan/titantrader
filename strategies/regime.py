"""Market regime detection - know when to trade, when to sit out."""
import pandas as pd
import logging

logger = logging.getLogger(__name__)


class MarketRegime:
    """Detect market conditions: Trending, Range-bound, Volatile, or Dead."""

    @staticmethod
    def detect_regime(df: pd.DataFrame) -> dict:
        """Analyze price action to determine market regime.

        Returns: {
            'regime': 'TRENDING_UP' | 'TRENDING_DOWN' | 'RANGE_BOUND' | 'VOLATILE',
            'strength': 0.0-1.0 (how strong the regime is),
            'tradable': True/False (should we trade this symbol?)
        }
        """
        if len(df) < 50:
            return {'regime': 'UNKNOWN', 'strength': 0.0, 'tradable': False}

        close = df['Close']
        high = df['High']
        low = df['Low']
        volume = df['Volume']

        # ATR for volatility
        tr1 = high - low
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(14).mean()
        current_atr = atr.iloc[-1]
        atr_pct = (current_atr / close.iloc[-1]) * 100

        # Trend: EMA 20/50 crossover
        ema20 = close.ewm(span=20).mean()
        ema50 = close.ewm(span=50).mean()
        is_uptrend = ema20.iloc[-1] > ema50.iloc[-1]
        trend_distance = abs(ema20.iloc[-1] - ema50.iloc[-1]) / close.iloc[-1]

        # ADX for trend strength
        plus_dm = high.diff()
        minus_dm = -low.diff()
        plus_dm[plus_dm < 0] = 0
        minus_dm[minus_dm < 0] = 0

        tr14 = tr.rolling(14).sum()
        plus_di = 100 * (plus_dm.rolling(14).sum() / tr14)
        minus_di = 100 * (minus_dm.rolling(14).sum() / tr14)
        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di + 1e-6)
        adx = dx.rolling(14).mean()
        current_adx = adx.iloc[-1]

        # Range detection
        high_20 = high.rolling(20).max()
        low_20 = low.rolling(20).min()
        range_pct = ((high_20.iloc[-1] - low_20.iloc[-1]) / close.iloc[-1]) * 100

        # Volume trend
        vol_ma = volume.rolling(20).mean()
        vol_ratio = volume.iloc[-1] / vol_ma.iloc[-1]

        # Determine regime
        if current_adx > 25:  # Strong trend
            regime = 'TRENDING_UP' if is_uptrend else 'TRENDING_DOWN'
            strength = min(current_adx / 50, 1.0)
            tradable = True

        elif atr_pct > 4:  # High volatility but no trend
            regime = 'VOLATILE'
            strength = min(atr_pct / 6, 1.0)
            tradable = False  # Don't trade high vol without trend

        elif range_pct < 2:  # Tight range
            regime = 'RANGE_BOUND'
            strength = 1.0 - (range_pct / 3)
            tradable = False  # Choppy, avoid

        else:
            regime = 'NORMAL'
            strength = 0.7
            tradable = True

        return {
            'regime': regime,
            'strength': strength,
            'tradable': tradable,
            'adx': current_adx,
            'atr_pct': atr_pct,
            'is_uptrend': is_uptrend,
            'vol_ratio': vol_ratio
        }
