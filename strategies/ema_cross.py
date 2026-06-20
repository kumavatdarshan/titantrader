import pandas as pd
from strategies.base import Strategy, Signal
from strategies.regime import MarketRegime


class EMACrossStrategy(Strategy):
    """Trend-following strategy: EMA crossover with ADX confirmation."""
    name = "ema_cross"

    async def generate_signal(self, symbol: str, price_df: pd.DataFrame) -> Signal:
        """EMA(9/21) crossover + trend strength confirmation (ADX > 20).

        Only trade in strong uptrends or downtrends. Ignore choppy markets.
        """
        if len(price_df) < 50:
            return Signal(direction="HOLD", confidence=0.0, reasoning="Need 50 candles")

        close = price_df['Close']
        high = price_df['High']
        low = price_df['Low']
        volume = price_df['Volume']

        # Check market regime first
        regime_data = MarketRegime.detect_regime(price_df)
        if not regime_data['tradable']:
            return Signal(direction="HOLD", confidence=0.0,
                         reasoning=f"Market regime {regime_data['regime']} not tradable")

        # EMAs
        ema9 = close.ewm(span=9).mean()
        ema21 = close.ewm(span=21).mean()
        ema50 = close.ewm(span=50).mean()

        current_price = close.iloc[-1]
        current_ema9 = ema9.iloc[-1]
        current_ema21 = ema21.iloc[-1]
        current_ema50 = ema50.iloc[-1]
        prev_ema9 = ema9.iloc[-2]
        prev_ema21 = ema21.iloc[-2]

        # Volume confirmation
        vol_ma = volume.tail(20).mean()
        vol_ratio = volume.iloc[-1] / vol_ma if vol_ma > 0 else 1.0

        # Crossover detection
        crossover = prev_ema9 <= prev_ema21 and current_ema9 > current_ema21
        crossunder = prev_ema9 >= prev_ema21 and current_ema9 < current_ema21

        # Strong uptrend: EMA9 > EMA21 > EMA50
        if crossover and vol_ratio >= 0.8 and current_ema21 > current_ema50:
            confidence = min(0.75 * regime_data['strength'], 1.0)
            return Signal(
                direction="BUY",
                confidence=confidence,
                reasoning=f"EMA9↑EMA21 in uptrend, ADX={regime_data['adx']:.1f}"
            )

        # Strong downtrend: EMA9 < EMA21 < EMA50
        if crossunder and vol_ratio >= 0.8 and current_ema21 < current_ema50:
            confidence = min(0.75 * regime_data['strength'], 1.0)
            return Signal(
                direction="SELL",
                confidence=confidence,
                reasoning=f"EMA9↓EMA21 in downtrend, ADX={regime_data['adx']:.1f}"
            )

        return Signal(direction="HOLD", confidence=0.0, reasoning="No strong crossover")
