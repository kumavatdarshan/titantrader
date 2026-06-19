import pandas as pd
from strategies.base import Strategy, Signal


class RSIReversionStrategy(Strategy):
    name = "rsi_reversion"

    async def generate_signal(self, symbol: str, price_df: pd.DataFrame) -> Signal:
        """Enhanced RSI mean reversion with momentum confirmation."""
        if len(price_df) < 21:
            return Signal(direction="HOLD", confidence=0.0, reasoning="Not enough candles (need 21)")

        close = price_df['Close']
        high = price_df['High']
        low = price_df['Low']

        rsi = self._calculate_rsi(close, 14)
        current_rsi = rsi.iloc[-1]
        prev_rsi = rsi.iloc[-2]

        sma20 = close.rolling(20).mean()
        std20 = close.rolling(20).std()
        upper_bb = sma20 + (std20 * 2)
        lower_bb = sma20 - (std20 * 2)
        sma50 = close.rolling(50).mean()

        current_price = close.iloc[-1]
        current_lower = lower_bb.iloc[-1]
        current_upper = upper_bb.iloc[-1]

        hour = pd.Timestamp.now().hour
        if 9 <= hour < 10:
            return Signal(direction="HOLD", confidence=0.0, reasoning="Skip market open volatility")

        momentum = (close.iloc[-1] - close.iloc[-5]) / close.iloc[-5]
        strength = abs(current_rsi - 50) / 50

        if current_rsi < 25 and current_price < current_lower * 0.98 and momentum < -0.03:
            confidence = min((50 - current_rsi) / 25 * strength, 1.0)
            return Signal(
                direction="BUY",
                confidence=confidence,
                reasoning=f"Strong oversold: RSI={current_rsi:.1f}, momentum={momentum:.3f}, confidence={confidence:.2f}"
            )

        if current_rsi > 75 and current_price > current_upper * 1.02 and momentum > 0.03:
            confidence = min((current_rsi - 50) / 25 * strength, 1.0)
            return Signal(
                direction="SELL",
                confidence=confidence,
                reasoning=f"Strong overbought: RSI={current_rsi:.1f}, momentum={momentum:.3f}, confidence={confidence:.2f}"
            )

        if current_rsi < 35 and momentum < -0.01:
            confidence = min((50 - current_rsi) / 50 * 0.6, 0.5)
            return Signal(direction="BUY", confidence=confidence, reasoning=f"Oversold: RSI={current_rsi:.1f}")

        if current_rsi > 65 and momentum > 0.01:
            confidence = min((current_rsi - 50) / 50 * 0.6, 0.5)
            return Signal(direction="SELL", confidence=confidence, reasoning=f"Overbought: RSI={current_rsi:.1f}")

        return Signal(direction="HOLD", confidence=0.0, reasoning=f"RSI={current_rsi:.1f} - waiting for extremes")

    def _calculate_rsi(self, series, period=14):
        delta = series.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi
