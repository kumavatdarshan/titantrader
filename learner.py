import logging
import pickle
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime
from sqlalchemy import select
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import f1_score, precision_score, recall_score, roc_auc_score
from db import Trade, Lesson, Price, MLRun
from config import Config
import ta

logger = logging.getLogger(__name__)


class Learner:
    def __init__(self, session_factory):
        self.session_factory = session_factory
        self.last_accuracy = 0.0
        self.training_count = 0

    async def retrain_ml_model(self):
        """Daily ML retraining pipeline — self-improving with daily data."""
        logger.info("=" * 60)
        logger.info("ML RETRAINING CYCLE START")
        logger.info("=" * 60)

        async with self.session_factory() as session:
            # Get only SELL trades (closed trades with real P&L)
            result = await session.execute(select(Trade).where(Trade.side == "SELL"))
            sell_trades = result.scalars().all()

            if len(sell_trades) < Config.ML_MIN_TRADES_TO_TRAIN:
                logger.warning(f"Only {len(sell_trades)} closed trades. Need {Config.ML_MIN_TRADES_TO_TRAIN} to train.")
                return

            # Trade stats
            profitable_trades = sum(1 for t in sell_trades if (t.net_pnl or 0) > 0)
            losing_trades = len(sell_trades) - profitable_trades
            win_rate = profitable_trades / len(sell_trades) if sell_trades else 0
            avg_win = sum(t.net_pnl for t in sell_trades if (t.net_pnl or 0) > 0) / profitable_trades if profitable_trades > 0 else 0
            avg_loss = sum(abs(t.net_pnl) for t in sell_trades if (t.net_pnl or 0) < 0) / losing_trades if losing_trades > 0 else 0
            total_pnl = sum(t.net_pnl or 0 for t in sell_trades)

            logger.info(f"Training on {len(sell_trades)} SELL trades")
            logger.info(f"  Win rate: {win_rate*100:.1f}% | Avg win: ${avg_win:.2f} | Avg loss: ${avg_loss:.2f}")
            logger.info(f"  Total P&L: ${total_pnl:+.2f}")

            X, y, scaler = await self._prepare_features(sell_trades)
            if X is None or len(X) < 10:
                logger.error("Insufficient features for training")
                return

            X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)

            # Use LightGBM for better performance on NSE data
            if Config.ML_USE_LIGHTGBM:
                import lightgbm as lgb
                model = lgb.LGBMClassifier(
                    n_estimators=300,
                    learning_rate=0.05,
                    max_depth=6,
                    num_leaves=31,
                    subsample=0.8,
                    colsample_bytree=0.8,
                    class_weight='balanced',
                    random_state=42,
                    verbose=-1
                )
                logger.info("Using LightGBM classifier")
            else:
                from sklearn.ensemble import RandomForestClassifier
                model = RandomForestClassifier(
                    n_estimators=200,
                    max_depth=8,
                    class_weight='balanced',
                    random_state=42
                )
                logger.info("Using RandomForest classifier")

            model.fit(X_train, y_train)

            y_pred = model.predict(X_test)
            y_pred_proba = model.predict_proba(X_test)[:, 1]

            accuracy = model.score(X_test, y_test)
            f1 = f1_score(y_test, y_pred, zero_division=0)
            precision = precision_score(y_test, y_pred, zero_division=0)
            recall = recall_score(y_test, y_pred, zero_division=0)
            auc = roc_auc_score(y_test, y_pred_proba) if len(np.unique(y_test)) > 1 else 0.0
            self.last_accuracy = accuracy

            logger.info(f"Model performance:")
            logger.info(f"  Accuracy: {accuracy*100:.2f}% | F1: {f1:.4f} | Precision: {precision:.4f}")
            logger.info(f"  Recall: {recall:.4f} | AUC: {auc:.4f}")

            model_path = Path("models/predictor.pkl")
            model_path.parent.mkdir(exist_ok=True)
            with open(model_path, 'wb') as f:
                pickle.dump({'model': model, 'scaler': scaler}, f)

            # Dynamic accuracy threshold — improve as bot learns
            # Start at 55%, lower to 50% if we have >50 trades (confidence in data)
            dynamic_threshold = 0.50 if len(sell_trades) > 50 else Config.ML_MIN_ACCURACY
            was_deployed = accuracy >= dynamic_threshold

            ml_run = MLRun(
                accuracy=accuracy,
                f1_score=f1,
                n_samples=len(X),
                top_features=str(sorted(enumerate(model.feature_importances_), key=lambda x: x[1], reverse=True)[:3]),
                model_path=str(model_path),
                was_deployed=was_deployed
            )
            session.add(ml_run)
            await session.commit()

            if was_deployed:
                logger.info(f"✓ Model DEPLOYED (accuracy {accuracy*100:.2f}% >= {dynamic_threshold*100:.0f}%)")
            else:
                logger.warning(f"✗ Model NOT deployed (accuracy {accuracy*100:.2f}% < {dynamic_threshold*100:.0f}%)")

            # Log improvement
            lesson = Lesson(
                trigger="ML_TRAINING_COMPLETE",
                description=f"ML retrain on {len(sell_trades)} trades. Accuracy: {accuracy*100:.1f}%, Win rate: {win_rate*100:.1f}%, P&L: ${total_pnl:+.2f}",
                strategies_affected="ml_predictor",
                equity_at_time=0.0
            )
            session.add(lesson)
            await session.commit()

            logger.info("=" * 60)
            logger.info("ML RETRAINING CYCLE END")
            logger.info("=" * 60)

    async def _prepare_features(self, trades):
        """Extract real market technical features from price history at trade times."""
        try:
            if not trades:
                return None, None, None

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

                    # Calculate all technical indicators
                    rsi = self._calculate_rsi(closes)
                    macd, macd_signal = self._calculate_macd(closes)
                    bb_upper, bb_middle, bb_lower = self._calculate_bollinger(closes)
                    atr = self._calculate_atr(highs, lows, closes)

                    # Additional features for better prediction
                    momentum = (closes[-1] - closes[-5]) / np.maximum(closes[-5], 1e-10) if len(closes) >= 5 else 0
                    momentum_10 = (closes[-1] - closes[-10]) / np.maximum(closes[-10], 1e-10) if len(closes) >= 10 else 0

                    safe_closes = np.maximum(closes[:-1], 1e-10)
                    volatility = np.std(np.diff(closes) / safe_closes)

                    volume_ratio = volumes[-1] / np.mean(volumes) if len(volumes) > 0 else 1
                    volume_trend = np.mean(volumes[-5:]) / np.mean(volumes[-20:-5]) if len(volumes) >= 20 else 1

                    bb_position = (closes[-1] - bb_lower[-1]) / (bb_upper[-1] - bb_lower[-1]) if (bb_upper[-1] - bb_lower[-1]) != 0 else 0.5

                    # Price relative to moving averages
                    sma20 = np.mean(closes[-20:]) if len(closes) >= 20 else closes[-1]
                    sma50 = np.mean(closes[-50:]) if len(closes) >= 50 else closes[-1]
                    price_vs_sma20 = closes[-1] / np.maximum(sma20, 1e-10)
                    price_vs_sma50 = closes[-1] / np.maximum(sma50, 1e-10)

                    features_list.append({
                        'rsi': rsi[-1],
                        'macd': macd[-1],
                        'macd_signal': macd_signal[-1],
                        'bb_position': bb_position,
                        'atr': atr[-1],
                        'momentum': momentum,
                        'momentum_10': momentum_10,
                        'volatility': volatility,
                        'volume_ratio': volume_ratio,
                        'volume_trend': volume_trend,
                        'price_vs_sma20': price_vs_sma20,
                        'price_vs_sma50': price_vs_sma50,
                    })
                    # Target: 1 if trade was profitable, 0 if loss
                    targets.append(1 if (trade.net_pnl or 0) > 0 else 0)
                except Exception as e:
                    logger.debug(f"Skipping {trade.symbol}: {e}")
                    continue

            if len(features_list) < 10:
                logger.warning(f"Only {len(features_list)} trades with features. Need at least 10.")
                return None, None, None

            df = pd.DataFrame(features_list)
            targets_array = np.array(targets)

            df = df.fillna(df.median())

            if df.isnull().any().any():
                logger.warning("NaN values remain after fillna, dropping affected rows")
                valid_mask = ~df.isnull().any(axis=1)
                df = df[valid_mask]
                targets_array = targets_array[valid_mask]
                if len(df) < 10:
                    logger.error("Not enough valid data after NaN removal")
                    return None, None, None

            feature_cols = ['rsi', 'macd', 'macd_signal', 'bb_position', 'atr', 'momentum', 'momentum_10',
                          'volatility', 'volume_ratio', 'volume_trend', 'price_vs_sma20', 'price_vs_sma50']
            X = df[feature_cols].values
            y = targets_array

            scaler = StandardScaler()
            X = scaler.fit_transform(X)

            win_rate = y.mean() * 100
            logger.info(f"Prepared {len(X)} training samples with 12 technical features. Win rate: {win_rate:.1f}%")

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
