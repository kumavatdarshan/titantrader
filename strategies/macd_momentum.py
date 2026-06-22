import pandas as pd
from strategies.base import Strategy, Signal


class MACDMomentumStrategy(Strategy):
    name = "macd_momentum"

    async def generate_signal(self, symbol: str, price_df: pd.DataFrame) -> Signal:
        """MACD momentum with volume confirmation."""
        if len(price_df) < 30:
            return Signal(direction="HOLD", confidence=0.0, reasoning="Not enough candles")

        close = price_df['Close']
        volume = price_df['Volume']

        ema12 = close.ewm(span=12).mean()
        ema26 = close.ewm(span=26).mean()
        macd = ema12 - ema26
        signal_line = macd.ewm(span=9).mean()
        histogram = macd - signal_line

        current_macd = macd.iloc[-1]
        current_signal = signal_line.iloc[-1]
        current_hist = histogram.iloc[-1]
        prev_hist = histogram.iloc[-2]

        avg_vol = volume.tail(20).mean()
        current_vol = volume.iloc[-1]

        if current_vol < avg_vol * 0.5:
            return Signal(direction="HOLD", confidence=0.0, reasoning="Volume too low")

        atr = self._calculate_atr(price_df, 14)
        current_atr = atr.iloc[-1]
        confidence = abs(current_hist) / current_atr if current_atr > 0 else 0.0

        hist_positive = current_hist > 0
        hist_increasing = current_hist > prev_hist

        if current_macd > current_signal and hist_increasing:
            return Signal(
                direction="BUY",
                confidence=min(confidence * 0.8, 0.7),
                reasoning=f"MACD bullish cross, histogram increasing. Confidence: {confidence:.2f}"
            )

        if current_macd < current_signal and current_hist < prev_hist:
            return Signal(
                direction="SELL",
                confidence=min(confidence * 0.8, 0.7),
                reasoning=f"MACD bearish cross, histogram decreasing. Confidence: {confidence:.2f}"
            )

        return Signal(direction="HOLD", confidence=0.0, reasoning="No MACD momentum signal")

    def _calculate_atr(self, df, period=14):
        high_low = df['High'] - df['Low']
        high_close = abs(df['High'] - df['Close'].shift())
        low_close = abs(df['Low'] - df['Close'].shift())
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = ranges.max(axis=1)
        atr = true_range.rolling(period).mean()
        return atr
