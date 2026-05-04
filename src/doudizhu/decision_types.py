from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BidDecision:
    bid: int
    reason: str = ""


@dataclass(frozen=True)
class PlayDecision:
    cards: tuple[str, ...]
    reason: str = ""

    @property
    def is_pass(self) -> bool:
        return len(self.cards) == 0
