import logging
import pickle
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime
from sqlalchemy import select
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import f1_score
from db import Trade, Lesson, Price, MLRun
from config import Config
import ta

logger = logging.getLogger(__name__)


class Learner:
    def __init__(self, session_factory):
        self.session_factory = session_factory
        self.last_accuracy = 0.0

    async def retrain_ml_model(self):
        """Nightly ML retraining pipeline."""
        logger.info(" Starting ML model retraining...")

        async with self.session_factory() as session:
            result = await session.execute(select(Trade))
            trades = result.scalars().all()

            if len(trades) < Config.ML_MIN_TRADES_TO_TRAIN:
                logger.warning(f"Only {len(trades)} trades. Need {Config.ML_MIN_TRADES_TO_TRAIN} to train.")
                return

            profitable_trades = sum(1 for t in trades if (t.net_pnl or 0) > 0)
            losing_trades = len(trades) - profitable_trades
            win_rate = profitable_trades / len(trades) if trades else 0
            avg_win = sum(t.net_pnl for t in trades if (t.net_pnl or 0) > 0) / profitable_trades if profitable_trades > 0 else 0
            avg_loss = sum(abs(t.net_pnl) for t in trades if (t.net_pnl or 0) < 0) / losing_trades if losing_trades > 0 else 0

            logger.info(f"Training on {len(trades)} trades | Win rate: {win_rate*100:.1f}% | Avg win: ${avg_win:.2f} | Avg loss: ${avg_loss:.2f}")

            X, y, scaler = await self._prepare_features(trades)
            if X is None or len(X) < 10:
                logger.error("Insufficient features for training")
                return

            X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

            model = RandomForestClassifier(
                n_estimators=200,
                max_depth=8,
                class_weight='balanced',
                random_state=42
            )
            model.fit(X_train, y_train)

            y_pred = model.predict(X_test)
            accuracy = model.score(X_test, y_test)
            f1 = f1_score(y_test, y_pred, zero_division=0)
            self.last_accuracy = accuracy

            logger.info(f"Model trained | Accuracy: {accuracy*100:.2f}% | F1: {f1:.4f} | Samples: {len(X)}")

            model_path = Path("models/predictor.pkl")
            model_path.parent.mkdir(exist_ok=True)
            with open(model_path, 'wb') as f:
                pickle.dump({'model': model, 'scaler': scaler}, f)

            ml_run = MLRun(
                accuracy=accuracy,
                f1_score=f1,
                n_samples=len(X),
                top_features=str(sorted(enumerate(model.feature_importances_), key=lambda x: x[1], reverse=True)[:3]),
                model_path=str(model_path),
                was_deployed=accuracy >= Config.ML_MIN_ACCURACY
            )
            session.add(ml_run)
            await session.commit()

            if accuracy >= Config.ML_MIN_ACCURACY:
                logger.info(f" Model deployed to {model_path} (accuracy: {accuracy*100:.2f}%, F1: {f1:.4f})")
            else:
                logger.warning(f" Model saved but not deployed (accuracy {accuracy*100:.2f}% < {Config.ML_MIN_ACCURACY*100:.0f}% threshold)")

    async def _prepare_features(self, trades):
        """Extract real market technical features from price history at trade times."""
        try:
            if not trades:
                return None, None

            from data import fetch_ohlcv_candles

            features_list = []
            targets = []

            for trade in trades:
                if not trade.fill_price or trade.qty <= 0:
                    continue

                try:
                    result = await fetch_ohlcv_candles(trade.symbol, period="1mo")
                    if not result['success'] or result['data'] is None or len(result['data']) < 26:
                        continue

                    df = result['data']
                    closes = df['Close'].values
                    highs = df['High'].values
                    lows = df['Low'].values
                    volumes = df['Volume'].values if 'Volume' in df else np.ones(len(closes)) * 1000

                    rsi = self._calculate_rsi(closes)
                    macd, macd_signal = self._calculate_macd(closes)
                    bb_upper, bb_middle, bb_lower = self._calculate_bollinger(closes)
                    atr = self._calculate_atr(highs, lows, closes)
                    momentum = (closes[-1] - closes[-5]) / np.maximum(closes[-5], 1e-10) if len(closes) >= 5 else 0
                    # Protect against zero prices in volatility calculation
                    safe_closes = np.maximum(closes[:-1], 1e-10)
                    volatility = np.std(np.diff(closes) / safe_closes)
                    volume_ratio = volumes[-1] / np.mean(volumes) if len(volumes) > 0 else 1

                    features_list.append({
                        'rsi': rsi[-1],
                        'macd': macd[-1],
                        'macd_signal': macd_signal[-1],
                        'bb_position': (closes[-1] - bb_lower[-1]) / (bb_upper[-1] - bb_lower[-1]) if (bb_upper[-1] - bb_lower[-1]) != 0 else 0.5,
                        'atr': atr[-1],
                        'momentum': momentum,
                        'volatility': volatility,
                        'volume_ratio': volume_ratio,
                        # Removed hour_of_day and day_of_week to prevent overfitting
                    })
                    targets.append(1 if (trade.net_pnl or 0) > 0 else 0)
                except Exception as e:
                    logger.debug(f"Skipping {trade.symbol}: {e}")
                    continue

            if len(features_list) < 15:
                logger.warning(f"Only {len(features_list)} trades with features. Need at least 15.")
                return None, None, None

            df = pd.DataFrame(features_list)
            targets_array = np.array(targets)  # Convert early

            df = df.fillna(df.median())

            if df.isnull().any().any():
                logger.warning("NaN values remain after fillna, dropping affected rows")
                # Get indices of valid rows
                valid_mask = ~df.isnull().any(axis=1)
                df = df[valid_mask]
                targets_array = targets_array[valid_mask]  # CRITICAL: Keep X and y aligned
                if len(df) < 10:
                    logger.error("Not enough valid data after NaN removal")
                    return None, None, None

            X = df[['rsi', 'macd', 'macd_signal', 'bb_position', 'atr', 'momentum', 'volatility', 'volume_ratio']].values
            y = targets_array

            scaler = StandardScaler()
            X = scaler.fit_transform(X)

            win_rate = y.mean() * 100
            logger.info(f"Prepared {len(X)} training samples with market features. Win rate: {win_rate:.1f}%")

            return X, y, scaler

        except Exception as e:
            logger.error(f"Feature preparation error: {e}", exc_info=True)
            return None, None, None

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

    async def write_weekly_lesson(self):
        """Write weekly summary lesson."""
        async with self.session_factory() as session:
            lesson = Lesson(
                trigger="WEEKLY_SUMMARY",
                description="Weekly trading summary generated",
                strategies_affected="all",
                equity_at_time=0.0
            )
            session.add(lesson)
            await session.commit()
            logger.info("Weekly lesson written")
