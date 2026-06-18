import pytest
import asyncio
from broker.paper_broker import PaperBroker
from db import init_db, get_session_factory
from config import Config


@pytest.mark.asyncio
async def test_paper_broker_fee():
    """Test that fees are applied correctly."""
    engine = await init_db()
    session_factory = get_session_factory(engine)
    broker = PaperBroker(session_factory, 10000)

    order = await broker.place_order("AAPL", "BUY", 1.0)

    fee = order.fill_price * Config.FEE_RATE
    assert order.status == "FILLED"
    assert order.qty == 1.0

    await engine.dispose()
