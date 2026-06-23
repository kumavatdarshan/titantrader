from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


class DataUnavailableError(Exception):
    """Raised when price data is unavailable or stale."""
    pass


@dataclass
class Order:
    order_id: str
    symbol: str
    side: str
    qty: float
    fill_price: float
    status: str
    timestamp: datetime


class Broker(ABC):
    @abstractmethod
    async def get_price(self, symbol: str) -> dict:
        """Returns {'price': float, 'timestamp': datetime, 'source': str, 'is_stale': bool}"""
        pass

    @abstractmethod
    async def get_account(self) -> dict:
        """Returns {'cash': float, 'portfolio_value': float, 'buying_power': float}"""
        pass

    @abstractmethod
    async def place_order(self, symbol: str, side: str, qty: float, order_type: str = "market") -> Order:
        """side: BUY or SELL"""
        pass

    @abstractmethod
    async def get_positions(self) -> list:
        """Returns list of {'symbol': str, 'qty': float, 'avg_price': float}"""
        pass

    @abstractmethod
    async def get_order_status(self, order_id: str) -> str:
        """Returns status: PENDING, FILLED, REJECTED"""
        pass

    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool:
        pass

    @abstractmethod
    async def check_stops_and_exits(self, current_prices: dict) -> list:
        """Check and execute stop-loss and take-profit orders. Returns list of closed positions."""
        pass
