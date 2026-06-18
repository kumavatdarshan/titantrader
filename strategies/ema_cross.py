import pandas as pd
from strategies.base import Strategy, Signal


class EMACrossStrategy(Strategy):
    name = "ema_cross"

    async def generate_signal(self, symbol: str, price_df: pd.DataFrame) -> Signal:
        """EMA(9) and EMA(21) crossover strategy."""
        if len(price_df) < 30:
            return Signal(direction="HOLD", confidence=0.0, reasoning="Not enough candles (need 30)")

        close = price_df['Close']
        ema9 = close.ewm(span=9).mean()
        ema21 = close.ewm(span=21).mean()

        current_ema9 = ema9.iloc[-1]
        current_ema21 = ema21.iloc[-1]
        prev_ema9 = ema9.iloc[-2]
        prev_ema21 = ema21.iloc[-2]

        confidence = abs(current_ema9 - current_ema21) / current_ema21

        if prev_ema9 <= prev_ema21 and current_ema9 > current_ema21:
            vol = price_df['Volume'].tail(20).mean()
            current_vol = price_df['Volume'].iloc[-1]
            if current_vol > vol:
                return Signal(
                    direction="BUY",
                    confidence=min(confidence, 1.0),
                    reasoning=f"EMA9 crossed above EMA21. Confidence: {confidence:.2f}"
                )

        if prev_ema9 >= prev_ema21 and current_ema9 < current_ema21:
            return Signal(
                direction="SELL",
                confidence=min(confidence, 1.0),
                reasoning=f"EMA9 crossed below EMA21. Confidence: {confidence:.2f}"
            )

        return Signal(direction="HOLD", confidence=0.0, reasoning="No crossover detected")
