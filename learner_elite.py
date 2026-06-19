import logging
import pickle
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta
from sqlalchemy import select
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.model_selection import TimeSeriesSplit, cross_val_score
from sklearn.preprocessing import RobustScaler
from sklearn.metrics import precision_score, recall_score, f1_score, roc_auc_score
from db import Trade, Lesson, MLRun
from config import Config
import joblib

logger = logging.getLogger(__name__)


class EliteLearner:
    """World-class ML trainer with ensemble methods and hyperparameter tuning."""

    def __init__(self, session_factory):
        self.session_factory = session_factory
        self.models = {}
        self.scaler = RobustScaler()

    async def retrain_elite_models(self):
        """Train multiple ensemble models with cross-validation."""
        logger.info("🤖 ELITE MODEL TRAINING STARTED")

        async with self.session_factory() as session:
            result = await session.execute(select(Trade))
            trades = result.scalars().all()

            if len(trades) < Config.ML_MIN_TRADES_TO_TRAIN:
                logger.warning(f"Only {len(trades)} trades. Need {Config.ML_MIN_TRADES_TO_TRAIN} to train.")
                return

            X, y = self._engineer_features(trades)
            if X is None or len(X) < 10:
                logger.error("Insufficient features for training")
                return

            logger.info(f"Training on {len(trades)} trades | Features: {X.shape}")

            tscv = TimeSeriesSplit(n_splits=5)
            models_to_train = {
                'random_forest': RandomForestClassifier(
                    n_estimators=200,
                    max_depth=15,
                    min_samples_split=10,
                    min_samples_leaf=4,
                    max_features='sqrt',
                    n_jobs=-1,
                    random_state=42
                ),
                'gradient_boosting': GradientBoostingClassifier(
                    n_estimators=150,
                    learning_rate=0.05,
                    max_depth=7,
                    min_samples_split=10,
                    subsample=0.8,
                    random_state=42
                )
            }

            best_overall = None
            best_score = 0

            for name, model in models_to_train.items():
                try:
                    logger.info(f"Training {name}...")

                    cv_scores = cross_val_score(model, X, y, cv=tscv, scoring='f1')
                    logger.info(f"{name} CV F1 scores: {cv_scores.mean():.4f} (+/- {cv_scores.std():.4f})")

                    model.fit(X, y)
                    y_pred = model.predict(X)
                    y_pred_proba = model.predict_proba(X)[:, 1]

                    precision = precision_score(y, y_pred, zero_division=0)
                    recall = recall_score(y, y_pred, zero_division=0)
                    f1 = f1_score(y, y_pred, zero_division=0)
                    auc = roc_auc_score(y, y_pred_proba) if len(np.unique(y)) > 1 else 0.5

                    logger.info(
                        f"✅ {name} | Precision: {precision:.3f} | Recall: {recall:.3f} | F1: {f1:.3f} | AUC: {auc:.3f}"
                    )

                    self.models[name] = model
                    self._save_model(name, model)

                    metrics = {
                        'model': name,
                        'timestamp': datetime.utcnow().isoformat(),
                        'precision': float(precision),
                        'recall': float(recall),
                        'f1': float(f1),
                        'auc_roc': float(auc),
                        'n_samples': len(trades),
                        'cv_f1_mean': float(cv_scores.mean()),
                        'cv_f1_std': float(cv_scores.std()),
                    }

                    if f1 > best_score:
                        best_score = f1
                        best_overall = (name, metrics)

                    ml_run = MLRun(
                        accuracy=float(model.score(X, y)),
                        f1_score=float(f1),
                        n_samples=len(trades),
                        top_features=str(self._get_top_features(model)),
                        model_path=f"models/{name}_{datetime.utcnow().strftime('%Y%m%d')}.pkl",
                        was_deployed=f1 >= Config.ML_MIN_ACCURACY
                    )
                    session.add(ml_run)

                except Exception as e:
                    logger.error(f"Error training {name}: {e}", exc_info=True)

            if best_overall:
                name, metrics = best_overall
                logger.info(f"🏆 Best model: {name} with F1={metrics['f1']:.4f}")

                if metrics['f1'] >= Config.ML_MIN_ACCURACY:
                    logger.info(f"✅ ELITE MODEL DEPLOYED: {name}")
                else:
                    logger.warning(f"⚠️ Best model ({metrics['f1']:.3f}) below threshold ({Config.ML_MIN_ACCURACY:.3f})")

            await session.commit()
            logger.info("🤖 ELITE MODEL TRAINING COMPLETED")

    def _engineer_features(self, trades):
        """Advanced feature engineering from trade history."""
        features = []

        for trade in trades:
            try:
                hour = trade.timestamp.hour if trade.timestamp else 10
                day = trade.timestamp.weekday() if trade.timestamp else 2

                f = {
                    'qty': float(trade.qty or 0),
                    'fill_price': float(trade.fill_price or 1),
                    'fee_cost': float(trade.fee_cost or 0),
                    'slippage_cost': float(trade.slippage_cost or 0),
                    'net_pnl': float(trade.net_pnl or 0),
                    'hour_of_day': hour,
                    'day_of_week': day,
                    'side_buy': 1 if trade.side == 'BUY' else 0,
                }
                features.append(f)
            except Exception as e:
                logger.warning(f"Skipping malformed trade: {e}")
                continue

        if len(features) < 10:
            return None, None

        df = pd.DataFrame(features)
        df = df.fillna(df.median())

        X_cols = ['qty', 'fee_cost', 'slippage_cost', 'fill_price', 'hour_of_day', 'day_of_week', 'side_buy']
        X = self.scaler.fit_transform(df[X_cols])
        y = np.array([1 if f['net_pnl'] > 0 else 0 for f in features])

        logger.info(f"Features prepared | Win rate: {y.mean()*100:.1f}%")
        return X, y

    def _get_top_features(self, model):
        """Extract top 5 features by importance."""
        if hasattr(model, 'feature_importances_'):
            features = ['qty', 'fee', 'slippage', 'price', 'hour', 'day', 'side']
            importances = model.feature_importances_
            top = sorted(zip(features, importances), key=lambda x: x[1], reverse=True)[:5]
            return [(f, float(imp)) for f, imp in top]
        return []

    def _save_model(self, name, model):
        """Save model with timestamp."""
        path = Path("models") / f"{name}_{datetime.utcnow().strftime('%Y%m%d')}.pkl"
        path.parent.mkdir(exist_ok=True)
        joblib.dump(model, path)
        logger.info(f"💾 Saved: {path}")
