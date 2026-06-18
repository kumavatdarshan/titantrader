import pandas as pd
from strategies.base import Strategy, Signal


class RSIReversionStrategy(Strategy):
    name = "rsi_reversion"

    async def generate_signal(self, symbol: str, price_df: pd.DataFrame) -> Signal:
        """RSI mean reversion with Bollinger Band confirmation."""
        if len(price_df) < 30:
            return Signal(direction="HOLD", confidence=0.0, reasoning="Not enough candles")

        close = price_df['Close']

        rsi = self._calculate_rsi(close, 14)
        current_rsi = rsi.iloc[-1]

        sma = close.rolling(20).mean()
        std = close.rolling(20).std()
        upper_bb = sma + (std * 2)
        lower_bb = sma - (std * 2)

        current_price = close.iloc[-1]
        current_lower = lower_bb.iloc[-1]
        current_upper = upper_bb.iloc[-1]

        hour = pd.Timestamp.now().hour
        if 9 <= hour <= 9.5:
            return Signal(direction="HOLD", confidence=0.0, reasoning="Skip first 30min of market open")

        confidence = abs(current_rsi - 50) / 50

        if current_rsi < 30 and current_price <= current_lower:
            return Signal(
                direction="BUY",
                confidence=min(confidence, 1.0),
                reasoning=f"RSI={current_rsi:.1f} < 30, price at lower BB. Confidence: {confidence:.2f}"
            )

        if current_rsi > 70 and current_price >= current_upper:
            return Signal(
                direction="SELL",
                confidence=min(confidence, 1.0),
                reasoning=f"RSI={current_rsi:.1f} > 70, price at upper BB. Confidence: {confidence:.2f}"
            )

        return Signal(direction="HOLD", confidence=0.0, reasoning=f"RSI={current_rsi:.1f} neutral")

    def _calculate_rsi(self, series, period=14):
        delta = series.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi
