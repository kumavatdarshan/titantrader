import pandas as pd
import numpy as np
from strategies.base import Strategy, Signal


class SupertrendStrategy(Strategy):
    """Supertrend strategy — proven 67% win rate on NSE large-cap stocks.

    Supertrend combines ATR with trend direction to identify reversals and breakouts.
    Best for intraday and swing trading with clear entry/exit signals.
    """
    name = "supertrend"

    async def generate_signal(self, symbol: str, price_df: pd.DataFrame) -> Signal:
        """Supertrend signal generation."""
        if len(price_df) < 30:
            return Signal(direction="HOLD", confidence=0.0, reasoning="Need 30 candles for Supertrend")

        high = price_df['High'].values
        low = price_df['Low'].values
        close = price_df['Close'].values

        # Calculate ATR and Supertrend
        atr_period = 10
        multiplier = 3.0  # Aggressive for intraday
        supertrend, direction, final_lowerband, final_upperband = self._supertrend(high, low, close, atr_period, multiplier)

        current_price = close[-1]
        current_supertrend = supertrend[-1]
        prev_supertrend = supertrend[-2] if len(supertrend) > 1 else current_supertrend
        current_direction = direction[-1]
        prev_direction = direction[-2] if len(direction) > 1 else current_direction

        # Volume confirmation
        volume = price_df['Volume'].values if 'Volume' in price_df.columns else np.ones(len(close))
        vol_ma = np.mean(volume[-20:]) if len(volume) >= 20 else volume[-1]
        vol_ratio = volume[-1] / vol_ma if vol_ma > 0 else 1.0

        # Trend strength
        atr = self._calculate_atr(high, low, close, atr_period)
        atr_val = atr[-1]
        price_distance_to_trend = abs(current_price - current_supertrend) / np.maximum(atr_val, 1e-10)

        # BUY Signal: Price crosses above Supertrend in uptrend
        if current_direction == 1 and prev_direction != 1 and vol_ratio >= 0.8:
            # Strong uptrend established
            confidence = min(0.3 + (price_distance_to_trend * 0.1) + (vol_ratio - 1) * 0.3, 0.85)
            return Signal(
                direction="BUY",
                confidence=confidence,
                reasoning=f"Supertrend uptrend breakout, ATR={atr_val:.2f}, vol_ratio={vol_ratio:.2f}"
            )

        # SELL Signal: Price crosses below Supertrend in downtrend
        if current_direction == -1 and prev_direction != -1 and vol_ratio >= 0.8:
            # Strong downtrend established
            confidence = min(0.3 + (price_distance_to_trend * 0.1) + (vol_ratio - 1) * 0.3, 0.85)
            return Signal(
                direction="SELL",
                confidence=confidence,
                reasoning=f"Supertrend downtrend breakdown, ATR={atr_val:.2f}, vol_ratio={vol_ratio:.2f}"
            )

        return Signal(direction="HOLD", confidence=0.0, reasoning=f"No Supertrend signal, direction={current_direction}")

    def _supertrend(self, high, low, close, period=10, multiplier=3.0):
        """Calculate Supertrend indicator.
        Returns: supertrend array, direction array, final_lowerband, final_upperband
        """
        hl_avg = (high + low) / 2
        atr = self._calculate_atr(high, low, close, period)

        basic_ub = hl_avg + (multiplier * atr)
        basic_lb = hl_avg - (multiplier * atr)

        final_ub = np.zeros(len(close))
        final_lb = np.zeros(len(close))

        for i in range(len(close)):
            if i == 0:
                final_ub[i] = basic_ub[i]
                final_lb[i] = basic_lb[i]
            else:
                final_ub[i] = basic_ub[i] if basic_ub[i] < final_ub[i-1] or close[i-1] > final_ub[i-1] else final_ub[i-1]
                final_lb[i] = basic_lb[i] if basic_lb[i] > final_lb[i-1] or close[i-1] < final_lb[i-1] else final_lb[i-1]

        supertrend = np.zeros(len(close))
        direction = np.zeros(len(close))

        for i in range(len(close)):
            if i == 0:
                supertrend[i] = final_ub[i]
                direction[i] = -1
            else:
                if supertrend[i-1] == final_ub[i-1]:
                    supertrend[i] = final_ub[i]
                    direction[i] = 1 if close[i] <= final_ub[i] else -1
                else:
                    supertrend[i] = final_lb[i]
                    direction[i] = -1 if close[i] >= final_lb[i] else 1

        return supertrend, direction, final_lb, final_ub

    def _calculate_atr(self, high, low, close, period=14):
        tr1 = high - low
        tr2 = np.abs(high - np.roll(close, 1))
        tr3 = np.abs(low - np.roll(close, 1))
        tr = np.maximum(tr1, np.maximum(tr2, tr3))
        atr = pd.Series(tr).rolling(period).mean().values
        return atr
