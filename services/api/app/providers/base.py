from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any

@dataclass
class Provenance:
    provider: str
    source_url: str | None
    captured_at: datetime

@dataclass
class ProviderValue:
    value: Any
    provenance: Provenance

class MarketDataProvider(ABC):
    @abstractmethod
    async def quote(self, ticker: str) -> ProviderValue: ...

class FundamentalsProvider(ABC):
    @abstractmethod
    async def financials(self, ticker: str) -> ProviderValue: ...
