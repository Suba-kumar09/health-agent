from __future__ import annotations

from abc import ABC, abstractmethod


class Collector(ABC):
    """Lifecycle contract shared by all collectors."""

    name: str

    @abstractmethod
    def start(self) -> None: ...

    @abstractmethod
    def stop(self) -> None: ...
