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
from db import Trade, Lesson, Price
from config import Config
import ta

logger = logging.getLogger(__name__)


class Learner:
    def __init__(self, session_factory):
        self.session_factory = session_factory
        self.last_accuracy = 0.0

    async def retrain_ml_model(self):
        """Nightly ML retraining pipeline."""
        logger.info("Starting ML model retraining...")

        async with self.session_factory() as session:
            result = await session.execute(select(Trade))
            trades = result.scalars().all()

            if len(trades) < Config.ML_MIN_TRADES_TO_TRAIN:
                logger.warning(f"Only {len(trades)} trades. Need {Config.ML_MIN_TRADES_TO_TRAIN} to train.")
                return

            logger.info(f"Training on {len(trades)} trades")

            X, y = await self._prepare_features(trades)
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

            accuracy = model.score(X_test, y_test)
            self.last_accuracy = accuracy

            logger.info(f"Model accuracy: {accuracy*100:.2f}%")

            if accuracy >= Config.ML_MIN_ACCURACY:
                model_path = Path("models/predictor.pkl")
                model_path.parent.mkdir(exist_ok=True)
                with open(model_path, 'wb') as f:
                    pickle.dump(model, f)
                logger.info(f"Model deployed to {model_path}")

                top_features = sorted(
                    enumerate(model.feature_importances_),
                    key=lambda x: x[1],
                    reverse=True
                )[:3]
                logger.info(f"Top features: {top_features}")

            else:
                logger.warning(f"Accuracy {accuracy*100:.2f}% < {Config.ML_MIN_ACCURACY*100:.0f}% threshold")

    async def _prepare_features(self, trades):
        """Extract real technical features from trade history."""
        try:
            if not trades:
                return None, None

            features_list = []
            targets = []

            for trade in trades:
                if not trade.fill_price or trade.qty <= 0:
                    continue

                entry_time = trade.timestamp
                hour = entry_time.hour
                day = entry_time.weekday()

                features_list.append({
                    'qty': trade.qty,
                    'fill_price': trade.fill_price,
                    'fee_cost': trade.fee_cost or 0,
                    'slippage_cost': trade.slippage_cost or 0,
                    'net_pnl': trade.net_pnl or 0,
                    'hour_of_day': hour,
                    'day_of_week': day,
                })
                targets.append(1 if (trade.net_pnl or 0) > 0 else 0)

            if len(features_list) < 10:
                logger.warning(f"Only {len(features_list)} trades with features. Need at least 10.")
                return None, None

            df = pd.DataFrame(features_list)
            df = df.fillna(df.median())

            X = df[['qty', 'fee_cost', 'slippage_cost', 'fill_price', 'hour_of_day', 'day_of_week']].values
            y = np.array(targets)

            scaler = StandardScaler()
            X = scaler.fit_transform(X)

            logger.info(f"Prepared {len(X)} training samples. Win rate: {y.mean()*100:.1f}%")

            return X, y

        except Exception as e:
            logger.error(f"Feature preparation error: {e}", exc_info=True)
            return None, None

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
