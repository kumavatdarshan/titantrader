import pandas as pd
from strategies.base import Strategy, Signal


class EMACrossStrategy(Strategy):
    name = "ema_cross"

    async def generate_signal(self, symbol: str, price_df: pd.DataFrame) -> Signal:
        """Enhanced EMA(9/21) crossover with trend confirmation."""
        if len(price_df) < 50:
            return Signal(direction="HOLD", confidence=0.0, reasoning="Not enough candles (need 50)")

        close = price_df['Close']
        high = price_df['High']
        low = price_df['Low']
        volume = price_df['Volume']

        ema9 = close.ewm(span=9).mean()
        ema21 = close.ewm(span=21).mean()
        ema50 = close.ewm(span=50).mean()

        current_price = close.iloc[-1]
        current_ema9 = ema9.iloc[-1]
        current_ema21 = ema21.iloc[-1]
        current_ema50 = ema50.iloc[-1]
        prev_ema9 = ema9.iloc[-2]
        prev_ema21 = ema21.iloc[-2]

        atr = self._calculate_atr(high, low, close)
        confidence = abs(current_ema9 - current_ema21) / current_ema21

        vol_ma = volume.tail(20).mean()
        current_vol = volume.iloc[-1]
        vol_ratio = current_vol / vol_ma if vol_ma > 0 else 1.0

        crossover = prev_ema9 <= prev_ema21 and current_ema9 > current_ema21
        crossunder = prev_ema9 >= prev_ema21 and current_ema9 < current_ema21

        if crossover and vol_ratio >= 0.8:
            if current_ema21 > current_ema50:
                final_conf = min(confidence * vol_ratio * 0.8, 1.0)
                return Signal(
                    direction="BUY",
                    confidence=final_conf,
                    reasoning=f"EMA9↑EMA21, uptrend (EMA21>{current_ema50:.2f}), vol:{vol_ratio:.2f}x"
                )

        if crossunder and vol_ratio >= 0.8:
            if current_ema21 < current_ema50:
                final_conf = min(confidence * vol_ratio * 0.8, 1.0)
                return Signal(
                    direction="SELL",
                    confidence=final_conf,
                    reasoning=f"EMA9↓EMA21, downtrend (EMA21<{current_ema50:.2f}), vol:{vol_ratio:.2f}x"
                )

        return Signal(direction="HOLD", confidence=0.0, reasoning="No strong crossover or trend")

    def _calculate_atr(self, high, low, close, period=14):
        """Calculate Average True Range."""
        tr1 = high - low
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return tr.rolling(period).mean()
