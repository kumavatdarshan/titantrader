from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class Signal:
    direction: str
    confidence: float
    reasoning: str


class Strategy(ABC):
    name: str

    @abstractmethod
    async def generate_signal(self, symbol: str, price_df) -> Signal:
        """
        Returns Signal with direction (BUY/SELL/HOLD),
        confidence (0-1), and reasoning.
        """
        pass
