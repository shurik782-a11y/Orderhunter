from abc import ABC, abstractmethod

from app.core.normalizer import NormalizedOrder


class BaseConnector(ABC):
    name: str = "base"

    @abstractmethod
    async def poll(self) -> list[NormalizedOrder]:
        ...
