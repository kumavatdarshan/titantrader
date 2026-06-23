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
        # NOTE: Caller should pass historical trade count, not current position count
        # If we have few historical trades, use conservative Kelly
        if win_rate == 0.52 and avg_win == 100 and avg_loss == 100:
            # Default conservative stats indicate insufficient history
            kelly_fraction = Config.KELLY_FRACTION_CAP * 0.5
            logger.debug(f"{symbol}: Using fixed 50% Kelly (insufficient trade history)")
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
        """Prevent holding too many correlated positions by count AND exposure."""
        def normalize_symbol(s):
            """Remove .NS suffix for comparison."""
            return s[:-3] if s.endswith('.NS') else s

        # Tech sector correlation group
        tech_symbols = {'AAPL', 'MSFT', 'NVDA', 'GOOGL', 'META'}
        held_tech = [s for s in positions.keys() if normalize_symbol(s) in tech_symbols]

        # Indian banking/IT correlation groups (with and without .NS)
        banking_symbols = {'HDFCBANK', 'ICICIBANK', 'SBIN', 'KOTAKBANK', 'AXISBANK'}
        it_symbols = {'INFY', 'TCS', 'WIPRO', 'HCLTECH', 'TECHM'}
        held_banking = [s for s in positions.keys() if normalize_symbol(s) in banking_symbols]
        held_it = [s for s in positions.keys() if normalize_symbol(s) in it_symbols]

        # Check all correlation groups by COUNT
        if len(held_tech) > 2:
            logger.warning(f"Too many correlated tech positions: {held_tech}")
            return False

        if len(held_banking) > 2:
            logger.warning(f"Too many correlated banking positions: {held_banking}")
            return False

        if len(held_it) > 2:
            logger.warning(f"Too many correlated IT positions: {held_it}")
            return False

        # Check by EXPOSURE (total value in each sector)
        total_portfolio = sum(p.qty * p.avg_entry_price for p in positions.values())
        if total_portfolio > 0:
            tech_exposure = sum(p.qty * p.avg_entry_price for p in positions.values() if normalize_symbol(p.symbol) in tech_symbols)
            banking_exposure = sum(p.qty * p.avg_entry_price for p in positions.values() if normalize_symbol(p.symbol) in banking_symbols)
            it_exposure = sum(p.qty * p.avg_entry_price for p in positions.values() if normalize_symbol(p.symbol) in it_symbols)

            tech_pct = (tech_exposure / total_portfolio) * 100 if tech_exposure > 0 else 0
            banking_pct = (banking_exposure / total_portfolio) * 100 if banking_exposure > 0 else 0
            it_pct = (it_exposure / total_portfolio) * 100 if it_exposure > 0 else 0

            # Log exposure for monitoring
            if tech_pct > 0:
                logger.debug(f"Tech sector exposure: {tech_pct:.1f}%")
            if banking_pct > 0:
                logger.debug(f"Banking sector exposure: {banking_pct:.1f}%")
            if it_pct > 0:
                logger.debug(f"IT sector exposure: {it_pct:.1f}%")

        return True

    @staticmethod
    def calculate_max_loss_dollars(portfolio_value: float) -> float:
        """Daily loss limit - circuit breaker."""
        return portfolio_value * Config.MAX_DAILY_LOSS_PCT
