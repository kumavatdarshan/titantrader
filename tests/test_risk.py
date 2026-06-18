import pytest
from risk import PositionSizer
from config import Config


def test_kelly_fraction_cap():
    """Test Kelly fraction is capped."""
    kelly = PositionSizer.calculate_kelly(win_rate=0.70, avg_win=5.0, avg_loss=1.0)
    assert kelly <= Config.KELLY_FRACTION_CAP


def test_position_size_limit():
    """Test position size respects MAX_POSITION_PCT."""
    qty = PositionSizer.calculate_position_size(
        portfolio_value=10000,
        cash=10000,
        symbol="AAPL",
        win_rate=0.55,
        avg_win=100,
        avg_loss=100,
        current_price=210,
        existing_positions={}
    )

    position_value = qty * 210
    max_allowed = 10000 * Config.MAX_POSITION_PCT

    assert position_value <= max_allowed * 1.01  # Allow 1% rounding error
