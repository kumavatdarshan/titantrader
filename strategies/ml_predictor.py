import pandas as pd
import logging
from pathlib import Path
from strategies.base import Strategy, Signal

logger = logging.getLogger(__name__)


class MLPredictorStrategy(Strategy):
    name = "ml_predictor"

    def __init__(self, min_accuracy=0.55):
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
        """ML-based buy/sell prediction."""
        if self.model is None or self.last_accuracy < self.min_accuracy:
            return Signal(
                direction="HOLD",
                confidence=0.0,
                reasoning=f"ML model unavailable or accuracy {self.last_accuracy:.2f}% < {self.min_accuracy*100:.0f}%"
            )

        if len(price_df) < 50:
            return Signal(direction="HOLD", confidence=0.0, reasoning="Not enough history for ML")

        try:
            features = self._extract_features(price_df)
            if features is None:
                return Signal(direction="HOLD", confidence=0.0, reasoning="Could not extract features")

            prediction = self.model.predict_proba(features.reshape(1, -1))
            prob_profit = prediction[0][1]

            if prob_profit > 0.60:
                return Signal(
                    direction="BUY",
                    confidence=prob_profit,
                    reasoning=f"ML predicts {prob_profit*100:.1f}% chance of profit"
                )

            if prob_profit < 0.40:
                return Signal(
                    direction="SELL",
                    confidence=1 - prob_profit,
                    reasoning=f"ML predicts {(1-prob_profit)*100:.1f}% chance of loss"
                )

            return Signal(direction="HOLD", confidence=0.5, reasoning=f"ML neutral ({prob_profit*100:.1f}%)")

        except Exception as e:
            logger.error(f"ML prediction error: {e}")
            return Signal(direction="HOLD", confidence=0.0, reasoning="ML prediction failed")

    def _extract_features(self, df):
        """Extract ML features matching learner training format: qty, fee_cost, slippage_cost, fill_price, hour, day."""
        try:
            close = df['Close']
            hour = pd.Timestamp.now().hour
            day = pd.Timestamp.now().dayofweek

            avg_price = close.iloc[-1]
            volatility = close.pct_change().std()
            volume_avg = df['Volume'].rolling(20).mean().iloc[-1] if 'Volume' in df else 1000

            features = [
                volume_avg / 1000,
                volatility * 100,
                volatility * 50,
                avg_price,
                hour,
                day,
            ]

            return pd.Series(features)

        except Exception as e:
            logger.error(f"Feature extraction error: {e}")
            return None

    def _rsi(self, series, period=14):
        delta = series.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss.replace(0, 1e-10)
        rsi = 100 - (100 / (1 + rs))
        return rsi.fillna(50)

    def _atr(self, df, period=14):
        high_low = df['High'] - df['Low']
        high_close = abs(df['High'] - df['Close'].shift())
        low_close = abs(df['Low'] - df['Close'].shift())
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = ranges.max(axis=1)
        atr = true_range.rolling(period).mean()
        return atr
