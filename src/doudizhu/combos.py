from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from itertools import combinations
from typing import Iterable

from .cards import CHAIN_RANKS, JOKERS, RANKS, RANK_VALUE, consecutive, format_cards, sort_cards


@dataclass(frozen=True)
class Combo:
    kind: str
    cards: tuple[str, ...]
    primary_value: int
    main_length: int = 1

    @property
    def size(self) -> int:
        return len(self.cards)

    @property
    def shape(self) -> tuple[str, int, int]:
        return (self.kind, self.size, self.main_length)

    @property
    def label(self) -> str:
        labels = {
            "single": "单张",
            "pair": "对子",
            "triple": "三张",
            "triple_single": "三带一",
            "triple_pair": "三带二",
            "straight": "顺子",
            "pair_straight": "连对",
            "triple_straight": "飞机",
            "airplane_single": "飞机带单",
            "airplane_pair": "飞机带对",
            "four_two_singles": "四带二",
            "four_two_pairs": "四带两对",
            "bomb": "炸弹",
            "rocket": "火箭",
        }
        return labels.get(self.kind, self.kind)

    def display(self) -> str:
        return f"{self.label} [{format_cards(self.cards)}]"


def _combo(kind: str, cards: Iterable[str], primary_rank: str, main_length: int = 1) -> Combo:
    sorted_cards = tuple(sort_cards(cards))
    return Combo(
        kind=kind,
        cards=sorted_cards,
        primary_value=RANK_VALUE[primary_rank],
        main_length=main_length,
    )


def _chain(values: Iterable[int]) -> bool:
    values = list(values)
    return all(RANKS[value] in CHAIN_RANKS for value in values) and consecutive(values)


def analyze_cards(cards: Iterable[str]) -> Combo | None:
    cards = list(cards)
    if not cards:
        return None

    counts = Counter(cards)
    if any(rank not in RANK_VALUE for rank in counts):
        return None

    size = len(cards)
    values = {rank: RANK_VALUE[rank] for rank in counts}
    count_values = sorted(counts.values(), reverse=True)
    ordered_ranks = sorted(counts, key=lambda rank: RANK_VALUE[rank])

    if size == 2 and all(counts.get(joker, 0) == 1 for joker in JOKERS):
        return _combo("rocket", cards, "RJ")

    if size == 4 and len(counts) == 1:
        return _combo("bomb", cards, ordered_ranks[0])

    if size == 1:
        return _combo("single", cards, ordered_ranks[0])

    if size == 2 and count_values == [2]:
        return _combo("pair", cards, ordered_ranks[0])

    if size == 3 and count_values == [3]:
        return _combo("triple", cards, ordered_ranks[0])

    if size == 4 and count_values == [3, 1]:
        triple_rank = next(rank for rank, count in counts.items() if count == 3)
        return _combo("triple_single", cards, triple_rank)

    if size == 5 and count_values == [3, 2]:
        triple_rank = next(rank for rank, count in counts.items() if count == 3)
        return _combo("triple_pair", cards, triple_rank)

    unique_values = [values[rank] for rank in ordered_ranks]
    if size >= 5 and all(count == 1 for count in counts.values()) and _chain(unique_values):
        return _combo("straight", cards, ordered_ranks[-1], main_length=size)

    if (
        size >= 6
        and size % 2 == 0
        and all(count == 2 for count in counts.values())
        and _chain(unique_values)
    ):
        return _combo("pair_straight", cards, ordered_ranks[-1], main_length=size // 2)

    if (
        size >= 6
        and size % 3 == 0
        and all(count == 3 for count in counts.values())
        and _chain(unique_values)
    ):
        return _combo("triple_straight", cards, ordered_ranks[-1], main_length=size // 3)

    if size >= 8 and size % 4 == 0:
        airplane = _analyze_airplane(cards, counts, wing_size=1)
        if airplane is not None:
            return airplane

    if size >= 10 and size % 5 == 0:
        airplane = _analyze_airplane(cards, counts, wing_size=2)
        if airplane is not None:
            return airplane

    if size == 6 and 4 in counts.values():
        bomb_rank = next(rank for rank, count in counts.items() if count == 4)
        if sum(count for rank, count in counts.items() if rank != bomb_rank) == 2:
            return _combo("four_two_singles", cards, bomb_rank)

    if size == 8 and 4 in counts.values():
        bomb_rank = next(rank for rank, count in counts.items() if count == 4)
        rest_counts = [count for rank, count in counts.items() if rank != bomb_rank]
        if sorted(rest_counts) == [2, 2]:
            return _combo("four_two_pairs", cards, bomb_rank)

    return None


def _analyze_airplane(cards: list[str], counts: Counter[str], wing_size: int) -> Combo | None:
    unit = 3 + wing_size
    main_length = len(cards) // unit
    if main_length < 2:
        return None

    triple_ranks = [
        rank
        for rank, count in counts.items()
        if count == 3 and rank in CHAIN_RANKS
    ]
    if len(triple_ranks) != main_length:
        return None

    triple_ranks.sort(key=lambda rank: RANK_VALUE[rank])
    triple_values = [RANK_VALUE[rank] for rank in triple_ranks]
    if not _chain(triple_values):
        return None

    rest = [
        count
        for rank, count in counts.items()
        if rank not in set(triple_ranks)
    ]
    if wing_size == 1 and sum(rest) == main_length:
        return _combo("airplane_single", cards, triple_ranks[-1], main_length=main_length)
    if wing_size == 2 and len(rest) == main_length and all(count == 2 for count in rest):
        return _combo("airplane_pair", cards, triple_ranks[-1], main_length=main_length)
    return None


def can_beat(candidate: Combo, target: Combo | None) -> bool:
    if target is None:
        return True
    if candidate.kind == "rocket":
        return target.kind != "rocket"
    if target.kind == "rocket":
        return False
    if candidate.kind == "bomb" and target.kind != "bomb":
        return True
    if target.kind == "bomb" and candidate.kind != "bomb":
        return False
    return candidate.shape == target.shape and candidate.primary_value > target.primary_value


def legal_plays(hand: Counter[str], target: Combo | None = None) -> list[Combo]:
    combos = generate_combos(hand)
    return sorted(
        [combo for combo in combos if can_beat(combo, target)],
        key=_play_sort_key,
    )


def generate_combos(hand: Counter[str]) -> list[Combo]:
    found: dict[tuple[str, ...], Combo] = {}

    def add(cards: Iterable[str]) -> None:
        combo = analyze_cards(cards)
        if combo is not None:
            found[combo.cards] = combo

    ranks = [rank for rank in RANKS if hand.get(rank, 0) > 0]

    for rank in ranks:
        add([rank])
        if hand[rank] >= 2:
            add([rank, rank])
        if hand[rank] >= 3:
            add([rank, rank, rank])
        if hand[rank] == 4:
            add([rank, rank, rank, rank])

    if all(hand.get(joker, 0) for joker in JOKERS):
        add(JOKERS)

    for triple_rank in [rank for rank in ranks if hand[rank] >= 3]:
        for single_rank in [rank for rank in ranks if rank != triple_rank and hand[rank] >= 1]:
            add([triple_rank] * 3 + [single_rank])
        for pair_rank in [rank for rank in ranks if rank != triple_rank and hand[rank] >= 2]:
            add([triple_rank] * 3 + [pair_rank] * 2)

    _add_chains(hand, width=1, min_length=5, add=add)
    _add_chains(hand, width=2, min_length=3, add=add)
    _add_chains(hand, width=3, min_length=2, add=add)
    _add_airplanes(hand, wing_size=1, add=add)
    _add_airplanes(hand, wing_size=2, add=add)
    _add_four_with_two(hand, add=add)

    return list(found.values())


def _play_sort_key(combo: Combo) -> tuple[int, int, int, int]:
    bomb_penalty = 1 if combo.kind in {"bomb", "rocket"} else 0
    return (bomb_penalty, combo.size, combo.primary_value, combo.main_length)


def _add_chains(hand: Counter[str], width: int, min_length: int, add) -> None:
    available = [rank for rank in CHAIN_RANKS if hand.get(rank, 0) >= width]
    available_values = [RANK_VALUE[rank] for rank in available]
    for start_index, start_value in enumerate(available_values):
        run: list[str] = []
        expected = start_value
        for rank in available[start_index:]:
            if RANK_VALUE[rank] != expected:
                break
            run.append(rank)
            expected += 1
            if len(run) >= min_length:
                cards: list[str] = []
                for chain_rank in run:
                    cards.extend([chain_rank] * width)
                add(cards)


def _add_airplanes(hand: Counter[str], wing_size: int, add) -> None:
    triple_ranks = [rank for rank in CHAIN_RANKS if hand.get(rank, 0) >= 3]
    for start in range(len(triple_ranks)):
        body: list[str] = []
        expected = RANK_VALUE[triple_ranks[start]]
        for rank in triple_ranks[start:]:
            if RANK_VALUE[rank] != expected:
                break
            body.append(rank)
            expected += 1
            if len(body) >= 2:
                cards = []
                for body_rank in body:
                    cards.extend([body_rank] * 3)
                body_set = set(body)
                if wing_size == 1:
                    counts = {
                        rank: hand[rank]
                        for rank in RANKS
                        if rank not in body_set and hand.get(rank, 0) > 0
                    }
                    for wings in _multiset_combinations(counts, len(body)):
                        add(cards + list(wings))
                else:
                    pair_ranks = [
                        pair_rank
                        for pair_rank in RANKS
                        if pair_rank not in body_set and hand.get(pair_rank, 0) >= 2
                    ]
                    for wings in combinations(pair_ranks, len(body)):
                        wing_cards: list[str] = []
                        for wing_rank in wings:
                            wing_cards.extend([wing_rank] * 2)
                        add(cards + wing_cards)


def _add_four_with_two(hand: Counter[str], add) -> None:
    for four_rank in [rank for rank in RANKS if hand.get(rank, 0) == 4]:
        rest_counts = {
            rank: hand[rank]
            for rank in RANKS
            if rank != four_rank and hand.get(rank, 0) > 0
        }
        for wings in _multiset_combinations(rest_counts, 2):
            add([four_rank] * 4 + list(wings))

        pair_ranks = [
            rank
            for rank in RANKS
            if rank != four_rank and hand.get(rank, 0) >= 2
        ]
        for pairs in combinations(pair_ranks, 2):
            cards: list[str] = [four_rank] * 4
            for pair_rank in pairs:
                cards.extend([pair_rank] * 2)
            add(cards)


def _multiset_combinations(counts: dict[str, int], total: int) -> list[tuple[str, ...]]:
    ranks = [rank for rank in RANKS if counts.get(rank, 0) > 0]
    results: list[tuple[str, ...]] = []

    def walk(index: int, remaining: int, current: list[str]) -> None:
        if remaining == 0:
            results.append(tuple(current))
            return
        if index >= len(ranks):
            return
        rank = ranks[index]
        max_take = min(counts[rank], remaining)
        for take in range(max_take + 1):
            current.extend([rank] * take)
            walk(index + 1, remaining - take, current)
            if take:
                del current[-take:]

    walk(0, total, [])
    return results
