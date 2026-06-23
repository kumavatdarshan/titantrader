import pandas as pd
from strategies.base import Strategy, Signal


class VolatilityBreakoutStrategy(Strategy):
    name = "volatility_breakout"

    async def generate_signal(self, symbol: str, price_df: pd.DataFrame) -> Signal:
        """Volatility-aware breakout strategy for ranging markets."""
        if len(price_df) < 30:
            return Signal(direction="HOLD", confidence=0.0, reasoning="Not enough candles")

        close = price_df['Close']
        high = price_df['High']
        low = price_df['Low']

        atr = self._calculate_atr(high, low, close, 14)
        current_atr = atr.iloc[-1]
        atr_sma = atr.rolling(20).mean().iloc[-1]

        highest_20 = high.rolling(20).max().iloc[-1]
        lowest_20 = low.rolling(20).min().iloc[-1]
        current_price = close.iloc[-1]

        volatility_ratio = current_atr / atr_sma if atr_sma > 0 else 1.0
        price_position = (current_price - lowest_20) / (highest_20 - lowest_20) if highest_20 > lowest_20 else 0.5

        # Protect against zero or negative prices
        safe_price_5 = max(close.iloc[-5], 1e-10)
        momentum = (close.iloc[-1] - close.iloc[-5]) / safe_price_5

        if volatility_ratio > 1.2 and price_position > 0.7 and momentum > 0.02:
            confidence = min((volatility_ratio - 1.0) * abs(momentum) * 0.8, 1.0)
            return Signal(
                direction="BUY",
                confidence=confidence,
                reasoning=f"High volatility breakout, vol_ratio={volatility_ratio:.2f}, momentum={momentum:.3f}"
            )

        if volatility_ratio > 1.2 and price_position < 0.3 and momentum < -0.02:
            confidence = min((volatility_ratio - 1.0) * abs(momentum) * 0.8, 1.0)
            return Signal(
                direction="SELL",
                confidence=confidence,
                reasoning=f"High volatility breakout down, vol_ratio={volatility_ratio:.2f}, momentum={momentum:.3f}"
            )

        return Signal(direction="HOLD", confidence=0.0, reasoning=f"Normal volatility (ratio={volatility_ratio:.2f})")

    def _calculate_atr(self, high, low, close, period=14):
        tr1 = high - low
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return tr.rolling(period).mean()
