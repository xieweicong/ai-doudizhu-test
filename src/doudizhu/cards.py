from __future__ import annotations

from collections import Counter
from typing import Iterable

RANKS: tuple[str, ...] = (
    "3",
    "4",
    "5",
    "6",
    "7",
    "8",
    "9",
    "10",
    "J",
    "Q",
    "K",
    "A",
    "2",
    "BJ",
    "RJ",
)
CHAIN_RANKS: tuple[str, ...] = RANKS[:12]
NORMAL_RANKS: tuple[str, ...] = RANKS[:13]
JOKERS: tuple[str, str] = ("BJ", "RJ")
RANK_VALUE: dict[str, int] = {rank: index for index, rank in enumerate(RANKS)}
VALUE_RANK: dict[int, str] = {value: rank for rank, value in RANK_VALUE.items()}
DISPLAY_RANK: dict[str, str] = {"BJ": "小王", "RJ": "大王"}


def new_deck() -> list[str]:
    deck: list[str] = []
    for rank in NORMAL_RANKS:
        deck.extend([rank] * 4)
    deck.extend(JOKERS)
    return deck


def validate_cards(cards: Iterable[str]) -> None:
    unknown = [card for card in cards if card not in RANK_VALUE]
    if unknown:
        raise ValueError(f"unknown card rank(s): {unknown}")


def sort_cards(cards: Iterable[str]) -> list[str]:
    validate_cards(cards)
    return sorted(cards, key=lambda card: (RANK_VALUE[card], card))


def cards_counter(cards: Iterable[str]) -> Counter[str]:
    cards = list(cards)
    validate_cards(cards)
    return Counter(cards)


def counter_to_cards(counter: Counter[str]) -> list[str]:
    cards: list[str] = []
    for rank in RANKS:
        cards.extend([rank] * counter.get(rank, 0))
    return cards


def format_cards(cards: Iterable[str]) -> str:
    sorted_cards = sort_cards(cards)
    return " ".join(DISPLAY_RANK.get(card, card) for card in sorted_cards) if sorted_cards else "-"


def format_counter(counter: Counter[str]) -> str:
    return format_cards(counter_to_cards(counter))


def has_cards(hand: Counter[str], cards: Iterable[str]) -> bool:
    requested = Counter(cards)
    return all(hand.get(rank, 0) >= count for rank, count in requested.items())


def remove_cards(hand: Counter[str], cards: Iterable[str]) -> Counter[str]:
    if not has_cards(hand, cards):
        raise ValueError(f"hand does not contain cards: {list(cards)}")
    new_hand = hand.copy()
    for rank, count in Counter(cards).items():
        new_hand[rank] -= count
        if new_hand[rank] <= 0:
            del new_hand[rank]
    return new_hand


def is_chain_value(value: int) -> bool:
    return VALUE_RANK[value] in CHAIN_RANKS


def consecutive(values: Iterable[int]) -> bool:
    ordered = sorted(values)
    return bool(ordered) and ordered == list(range(ordered[0], ordered[-1] + 1))
