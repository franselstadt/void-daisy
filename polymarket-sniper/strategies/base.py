"""Base strategy interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from core.state import AppState
from signals.composer import SignalComposer


class BaseStrategy(ABC):
    """Common interface for all strategy engines."""

    name: str

    def __init__(self, state: AppState, composer: SignalComposer) -> None:
        self.state = state
        self.composer = composer

    @abstractmethod
    async def evaluate(self, event: dict[str, Any]) -> dict[str, Any] | None:
        """Return opportunity payload when strategy conditions pass."""
