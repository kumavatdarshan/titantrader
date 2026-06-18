import pytest
from strategies.ema_cross import EMACrossStrategy
import pandas as pd


@pytest.mark.asyncio
async def test_ema_cross_strategy():
    """Test EMA crossover strategy."""
    strategy = EMACrossStrategy()

    closes = pd.Series([100 + i*0.1 for i in range(50)])
    df = pd.DataFrame({'Close': closes, 'Volume': [1000000] * 50})

    signal = await strategy.generate_signal("AAPL", df)

    assert signal.direction in ["BUY", "SELL", "HOLD"]
    assert 0 <= signal.confidence <= 1
    assert isinstance(signal.reasoning, str)
