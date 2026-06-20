import logging
from config import Config

logger = logging.getLogger(__name__)


class PositionSizer:
    """Professional position sizing: Risk 2% max per trade, use Kelly Criterion."""

    @staticmethod
    def calculate_kelly(win_rate: float, avg_win: float, avg_loss: float) -> float:
        """Kelly Criterion: f* = (b*p - q) / b where p=win%, q=loss%, b=win/loss."""
        if avg_win <= 0 or avg_loss <= 0 or win_rate <= 0:
            return 0.0

        p = min(max(win_rate, 0.0), 1.0)
        q = 1 - p
        b = avg_win / avg_loss
        kelly = (b * p - q) / b if b > 0 else 0.0
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
        existing_positions: dict,
        atr: float = None
    ) -> float:
        """Calculate position size using Risk Parity + Kelly Criterion.

        Risk: Max 2% of portfolio per trade (professional standard).
        """
        if cash <= 0 or portfolio_value <= 0 or current_price <= 0:
            return 0.0

        # Check position limits
        if len(existing_positions) >= Config.MAX_OPEN_POSITIONS:
            logger.warning(f"Max positions ({Config.MAX_OPEN_POSITIONS}) reached")
            return 0.0

        # ===== Risk-Based Position Sizing =====
        if atr:
            stop_level = current_price - (atr * Config.ATR_STOP_MULTIPLIER)
        else:
            stop_level = current_price * (1 - Config.STOP_LOSS_PCT)

        risk_per_share = current_price - stop_level
        if risk_per_share <= 0:
            logger.warning(f"{symbol}: Invalid risk calculation (stop={stop_level}, price={current_price})")
            return 0.0

        # 2% of portfolio
        max_risk_dollars = portfolio_value * Config.RISK_PER_TRADE_PCT
        qty_by_risk = max_risk_dollars / risk_per_share

        # ===== Kelly-Based Sizing =====
        if len(existing_positions) < Config.MIN_KELLY_TRADES:
            kelly_fraction = Config.KELLY_FRACTION_CAP * 0.5  # Conservative before we have data
            logger.debug(f"{symbol}: Using fixed 50% Kelly (< {Config.MIN_KELLY_TRADES} trades)")
        else:
            kelly_fraction = PositionSizer.calculate_kelly(win_rate, avg_win, avg_loss)

        qty_by_kelly = (portfolio_value * kelly_fraction) / current_price

        # Use whichever is SMALLER (more conservative)
        qty = min(qty_by_risk, qty_by_kelly)

        # Hard cap: 30% of portfolio in one position
        max_position = (portfolio_value * 0.30) / current_price
        qty = min(qty, max_position)

        # Can't buy more than cash allows
        qty = min(qty, cash / current_price)

        logger.info(f"{symbol}: Kelly={kelly_fraction:.1%}, Risk=${max_risk_dollars:.2f}, "
                   f"RiskQty={qty_by_risk:.4f}, KellyQty={qty_by_kelly:.4f}, Final={qty:.4f}")

        return max(qty, 0.0)

    @staticmethod
    def check_correlation(positions: dict) -> bool:
        """Prevent holding too many correlated positions."""
        if Config.is_angel_mode():
            # Indian market correlation groups
            banking_symbols = {'HDFCBANK', 'ICICIBANK', 'SBIN', 'KOTAKBANK', 'AXISBANK'}
            it_symbols = {'INFY', 'TCS', 'WIPRO', 'HCLTECH', 'TECHM'}

            held_banking = [s for s in positions.keys() if s in banking_symbols]
            held_it = [s for s in positions.keys() if s in it_symbols]

            if len(held_banking) > 2:
                logger.warning(f"Too many correlated banking positions: {held_banking}")
                return False

            if len(held_it) > 2:
                logger.warning(f"Too many correlated IT positions: {held_it}")
                return False
        else:
            # US market tech sector correlation group
            tech_symbols = {'AAPL', 'MSFT', 'NVDA', 'GOOGL', 'META'}
            held_tech = [s for s in positions.keys() if s in tech_symbols]

            if len(held_tech) > 2:
                logger.warning(f"Too many correlated tech positions: {held_tech}")
                return False

        return True

    @staticmethod
    def calculate_max_loss_dollars(portfolio_value: float) -> float:
        """Daily loss limit - circuit breaker."""
        return portfolio_value * Config.MAX_DAILY_LOSS_PCT
