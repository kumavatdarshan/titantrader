import logging
from config import Config

logger = logging.getLogger(__name__)


class PositionSizer:
    @staticmethod
    def calculate_kelly(win_rate: float, avg_win: float, avg_loss: float) -> float:
        """
        Kelly Criterion: f* = (win_rate * avg_win - (1-win_rate) * avg_loss) / avg_win
        Capped at KELLY_FRACTION_CAP
        """
        if avg_win <= 0 or avg_loss <= 0:
            return 0.0

        win_loss_ratio = avg_win / avg_loss
        kelly = (win_rate * win_loss_ratio - (1 - win_rate)) / win_loss_ratio
        kelly = max(0.0, min(kelly, Config.KELLY_FRACTION_CAP))

        return kelly

    @staticmethod
    def calculate_position_size(
        portfolio_value: float,
        cash: float,
        symbol: str,
        win_rate: float,
        avg_win: float,
        avg_loss: float,
        current_price: float,
        existing_positions: dict
    ) -> float:
        """
        Calculate how many shares/coins to buy.
        Returns qty to buy, or 0 if position can't be opened.
        """
        if cash <= 0:
            return 0.0

        if win_rate < 0.5 or len(existing_positions) >= Config.MAX_OPEN_POSITIONS:
            return 0.0

        if current_price <= 0:
            return 0.0

        if len(existing_positions) < Config.MIN_KELLY_TRADES:
            kelly_fraction = 0.02
            logger.info(f"Using fixed 2% sizing (< {Config.MIN_KELLY_TRADES} trades)")
        else:
            kelly_fraction = PositionSizer.calculate_kelly(win_rate, avg_win, avg_loss)

        max_value_per_position = portfolio_value * Config.MAX_POSITION_PCT
        position_value = min(kelly_fraction * portfolio_value, max_value_per_position, cash)

        qty = position_value / current_price

        logger.info(
            f"{symbol}: Kelly={kelly_fraction*100:.1f}%, "
            f"Max value=${max_value_per_position:.2f}, "
            f"Position value=${position_value:.2f}, "
            f"Qty={qty:.4f}"
        )

        return qty

    @staticmethod
    def validate_order(qty: float, symbol: str, current_price: float, cash: float) -> bool:
        """Verify the order is within limits."""
        if qty <= 0:
            return False

        cost = qty * current_price
        if cost > cash:
            logger.warning(f"{symbol}: Insufficient cash. Cost: ${cost:.2f}, Have: ${cash:.2f}")
            return False

        return True
