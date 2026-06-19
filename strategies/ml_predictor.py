import pandas as pd
import numpy as np
import logging
from pathlib import Path
from strategies.base import Strategy, Signal

logger = logging.getLogger(__name__)


class MLPredictorStrategy(Strategy):
    name = "ml_predictor"

    def __init__(self, min_accuracy=0.58):
        self.min_accuracy = min_accuracy
        self.model = None
        self.last_accuracy = 0.0
        self._load_model()

    def _load_model(self):
        """Load model from disk if it exists."""
        model_path = Path("models/predictor.pkl")
        if model_path.exists():
            try:
                import pickle
                with open(model_path, 'rb') as f:
                    self.model = pickle.load(f)
                logger.info(f"Loaded ML model from {model_path}")
            except Exception as e:
                logger.error(f"Failed to load model: {e}")
                self.model = None

    async def generate_signal(self, symbol: str, price_df: pd.DataFrame) -> Signal:
        """ML-based prediction using market features."""
        if self.model is None:
            return Signal(direction="HOLD", confidence=0.0, reasoning="ML model not trained yet")

        if len(price_df) < 30:
            return Signal(direction="HOLD", confidence=0.0, reasoning="Not enough history for ML")

        try:
            features = self._extract_features(price_df)
            if features is None:
                return Signal(direction="HOLD", confidence=0.0, reasoning="Could not extract features")

            prediction = self.model.predict_proba([features])
            prob_profit = prediction[0][1]

            if prob_profit > 0.62:
                return Signal(
                    direction="BUY",
                    confidence=min(prob_profit, 0.85),
                    reasoning=f"ML: {prob_profit*100:.1f}% profit probability"
                )

            if prob_profit < 0.38:
                return Signal(
                    direction="SELL",
                    confidence=min(1 - prob_profit, 0.85),
                    reasoning=f"ML: {(1-prob_profit)*100:.1f}% loss probability"
                )

            return Signal(direction="HOLD", confidence=0.0, reasoning=f"ML neutral ({prob_profit*100:.1f}%)")

        except Exception as e:
            logger.error(f"ML prediction error: {e}")
            return Signal(direction="HOLD", confidence=0.0, reasoning="ML error")

    def _extract_features(self, df):
        """Extract same features as training: RSI, MACD, Bollinger, ATR, momentum, etc."""
        try:
            closes = df['Close'].values
            highs = df['High'].values
            lows = df['Low'].values
            volumes = df['Volume'].values if 'Volume' in df else np.ones(len(closes)) * 1000

            if len(closes) < 26:
                return None

            rsi = self._calculate_rsi(closes)[-1]
            macd, macd_signal = self._calculate_macd(closes)
            bb_upper, bb_middle, bb_lower = self._calculate_bollinger(closes)
            atr = self._calculate_atr(highs, lows, closes)[-1]

            momentum = (closes[-1] - closes[-5]) / closes[-5] if len(closes) >= 5 else 0
            volatility = np.std(np.diff(closes) / closes[:-1])
            volume_ratio = volumes[-1] / np.mean(volumes) if len(volumes) > 0 else 1

            bb_position = (closes[-1] - bb_lower[-1]) / (bb_upper[-1] - bb_lower[-1]) if (bb_upper[-1] - bb_lower[-1]) != 0 else 0.5

            now = pd.Timestamp.now()
            hour = now.hour
            day = now.dayofweek

            features = [
                rsi,
                macd[-1],
                macd_signal[-1],
                bb_position,
                atr,
                momentum,
                volatility,
                volume_ratio,
                hour,
                day,
            ]

            return np.array(features)

        except Exception as e:
            logger.error(f"Feature extraction error: {e}")
            return None

    def _calculate_rsi(self, closes, period=14):
        delta = np.diff(closes)
        gain = np.where(delta > 0, delta, 0)
        loss = np.where(delta < 0, -delta, 0)
        avg_gain = np.convolve(gain, np.ones(period)/period, mode='valid')
        avg_loss = np.convolve(loss, np.ones(period)/period, mode='valid')
        rs = avg_gain / (avg_loss + 1e-10)
        rsi = 100 - (100 / (1 + rs))
        return np.concatenate([np.full(period, 50), rsi])

    def _calculate_macd(self, closes, fast=12, slow=26, signal=9):
        ema_fast = pd.Series(closes).ewm(span=fast).mean().values
        ema_slow = pd.Series(closes).ewm(span=slow).mean().values
        macd = ema_fast - ema_slow
        macd_signal = pd.Series(macd).ewm(span=signal).mean().values
        return macd, macd_signal

    def _calculate_bollinger(self, closes, period=20, num_std=2):
        sma = pd.Series(closes).rolling(period).mean().values
        std = pd.Series(closes).rolling(period).std().values
        upper = sma + (std * num_std)
        lower = sma - (std * num_std)
        return upper, sma, lower

    def _calculate_atr(self, highs, lows, closes, period=14):
        tr1 = highs - lows
        tr2 = np.abs(highs - np.roll(closes, 1))
        tr3 = np.abs(lows - np.roll(closes, 1))
        tr = np.maximum(tr1, np.maximum(tr2, tr3))
        atr = pd.Series(tr).rolling(period).mean().values
        return atr
