from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from random import Random
from typing import Any, Callable

from .ai import BaseAI, normalize_bid_decision, normalize_play_decision
from .cards import cards_counter, counter_to_cards, format_cards, format_counter, has_cards, new_deck, remove_cards
from .combos import Combo, analyze_cards, can_beat, legal_plays


@dataclass(frozen=True)
class GameConfig:
    seed: int | None = None
    expose_all_hands: bool = False
    max_turns: int = 1000
    redeal_limit: int = 50


@dataclass
class Player:
    seat: int
    name: str
    ai: BaseAI


@dataclass
class BidRecord:
    player: int
    bid: int
    reason: str = ""


@dataclass
class PlayRecord:
    turn: int
    player: int
    role: str
    cards: tuple[str, ...]
    combo: str = "pass"
    reason: str = ""
    invalid_reason: str = ""
    remaining: int = 0

    @property
    def is_pass(self) -> bool:
        return not self.cards


@dataclass
class GameResult:
    winner: int
    winner_side: str
    landlord: int
    farmers: tuple[int, int]
    bid: int
    multiplier: int
    spring: str | None
    points: dict[int, int]
    turns: int
    bottom_cards: tuple[str, ...]
    bids: list[BidRecord] = field(default_factory=list)
    plays: list[PlayRecord] = field(default_factory=list)
    initial_hands: dict[int, tuple[str, ...]] = field(default_factory=dict)
    redeals: int = 0


class DouDizhuGame:
    def __init__(
        self,
        players: list[Player],
        config: GameConfig | None = None,
        event_handler: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        if len(players) != 3:
            raise ValueError("Dou Dizhu requires exactly three players")
        self.players = players
        self.config = config or GameConfig()
        self.event_handler = event_handler
        self.rng = Random(self.config.seed)
        self.hands: list[Counter[str]] = [Counter() for _ in range(3)]
        self.initial_hands: dict[int, tuple[str, ...]] = {}
        self.bottom_cards: tuple[str, ...] = ()
        self.landlord: int | None = None
        self.farmers: tuple[int, int] = ()
        self.bid: int = 0
        self.bids: list[BidRecord] = []
        self.plays: list[PlayRecord] = []
        self.played_cards: list[str] = []
        self.redeals = 0
        self.bomb_or_rocket_count = 0

    def play(self) -> GameResult:
        self._deal_until_landlord()
        assert self.landlord is not None

        current = self.landlord
        last_combo: Combo | None = None
        last_player: int | None = None
        pass_count = 0

        for turn in range(1, self.config.max_turns + 1):
            legal = legal_plays(self.hands[current], last_combo)
            can_pass = last_combo is not None and last_player != current
            record, combo = self._ask_play(current, turn, legal, can_pass, last_combo, last_player)
            self.plays.append(record)

            if record.is_pass:
                self._emit("play_result", {"record": record})
                pass_count += 1
                if pass_count >= 2 and last_player is not None:
                    last_combo = None
                    pass_count = 0
                    current = last_player
                else:
                    current = (current + 1) % 3
                continue

            assert combo is not None
            self.hands[current] = remove_cards(self.hands[current], record.cards)
            self.played_cards.extend(record.cards)
            record.remaining = sum(self.hands[current].values())
            if combo.kind in {"bomb", "rocket"}:
                self.bomb_or_rocket_count += 1
            self._emit("play_result", {"record": record})

            if not self.hands[current]:
                return self._result(winner=current, turns=turn)

            last_combo = combo
            last_player = current
            pass_count = 0
            current = (current + 1) % 3

        raise RuntimeError(f"game exceeded max_turns={self.config.max_turns}")

    def _deal_until_landlord(self) -> None:
        for redeal in range(self.config.redeal_limit + 1):
            self.redeals = redeal
            self._deal_once()
            landlord = self._bid_for_landlord()
            if landlord is not None:
                self.landlord = landlord
                self.farmers = tuple(seat for seat in range(3) if seat != landlord)  # type: ignore[assignment]
                self.hands[landlord].update(self.bottom_cards)
                self._emit(
                    "landlord_selected",
                    {
                        "landlord": landlord,
                        "bid": self.bid,
                        "bottom_cards": self.bottom_cards,
                        "redeals": self.redeals,
                    },
                )
                return
            self._emit("redeal", {"redeals": self.redeals + 1})
        raise RuntimeError("all players passed too many times; no landlord selected")

    def _deal_once(self) -> None:
        deck = new_deck()
        self.rng.shuffle(deck)
        self.hands = [cards_counter(deck[index * 17 : (index + 1) * 17]) for index in range(3)]
        self.bottom_cards = tuple(deck[51:])
        self.initial_hands = {
            seat: tuple(counter_to_cards(hand))
            for seat, hand in enumerate(self.hands)
        }
        self.bids = []
        self.plays = []
        self.played_cards = []
        self.landlord = None
        self.farmers = ()
        self.bid = 0
        self.bomb_or_rocket_count = 0
        self._emit(
            "initial_deal",
            {
                "hands": self.initial_hands,
                "bottom_cards": self.bottom_cards,
            },
        )

    def _bid_for_landlord(self) -> int | None:
        starter = self.rng.randrange(3)
        highest_bid = 0
        landlord: int | None = None

        for offset in range(3):
            seat = (starter + offset) % 3
            valid_bids = [0] + [bid for bid in (1, 2, 3) if bid > highest_bid]
            view = self._view_for(seat, phase="bid", highest_bid=highest_bid)
            self._emit(
                "bid_thinking",
                {
                    "player": seat,
                    "hand": counter_to_cards(self.hands[seat]),
                    "valid_bids": valid_bids,
                    "highest_bid": highest_bid,
                },
            )
            try:
                raw_decision = self.players[seat].ai.choose_bid(view, valid_bids)
                decision = normalize_bid_decision(raw_decision, valid_bids)
            except Exception as error:
                decision = normalize_bid_decision(0, valid_bids)
                reason = f"AI 叫分异常: {_describe_exception(error)}"
                record = BidRecord(seat, decision.bid, reason)
                self.bids.append(record)
                self._emit("bid_result", {"record": record})
                continue

            record = BidRecord(seat, decision.bid, decision.reason)
            self.bids.append(record)
            self._emit("bid_result", {"record": record})
            if decision.bid > highest_bid:
                highest_bid = decision.bid
                landlord = seat
                if highest_bid == 3:
                    break

        self.bid = highest_bid
        return landlord

    def _ask_play(
        self,
        seat: int,
        turn: int,
        legal: list[Combo],
        can_pass: bool,
        last_combo: Combo | None,
        last_player: int | None,
    ) -> tuple[PlayRecord, Combo | None]:
        view = self._view_for(
            seat,
            phase="play",
            turn=turn,
            current_player=seat,
            can_pass=can_pass,
            last_combo=last_combo,
            last_player=last_player,
            current_trick=self._current_trick_view(last_combo, last_player, can_pass),
        )
        role = self._role_for(seat)
        self._emit(
            "play_thinking",
            {
                "turn": turn,
                "player": seat,
                "role": role,
                "hand": counter_to_cards(self.hands[seat]),
                "can_pass": can_pass,
                "last_combo": None if last_combo is None else last_combo.display(),
                "legal_count": len(legal),
            },
        )
        try:
            raw_decision = self.players[seat].ai.choose_play(view, legal, can_pass)
            decision = normalize_play_decision(raw_decision)
        except Exception as error:
            decision = normalize_play_decision(None)
            invalid_reason = f"AI 出牌异常: {_describe_exception(error)}"
        else:
            invalid_reason = ""

        combo = analyze_cards(decision.cards)
        valid = self._is_valid_play(seat, decision.cards, combo, last_combo, can_pass)
        if not valid:
            invalid_reason = invalid_reason or "非法出牌"
            if can_pass:
                return (
                    PlayRecord(
                        turn=turn,
                        player=seat,
                        role=role,
                        cards=(),
                        reason=decision.reason,
                        invalid_reason=invalid_reason,
                        remaining=sum(self.hands[seat].values()),
                    ),
                    None,
                )
            fallback = legal[0]
            return (
                PlayRecord(
                    turn=turn,
                    player=seat,
                    role=role,
                    cards=fallback.cards,
                    combo=fallback.label,
                    reason=decision.reason or "裁判兜底: 出第一手合法牌",
                    invalid_reason=invalid_reason,
                    remaining=sum(self.hands[seat].values()),
                ),
                fallback,
            )

        if decision.is_pass:
            return (
                PlayRecord(
                    turn=turn,
                    player=seat,
                    role=role,
                    cards=(),
                    reason=decision.reason,
                    remaining=sum(self.hands[seat].values()),
                ),
                None,
            )

        assert combo is not None
        return (
            PlayRecord(
                turn=turn,
                player=seat,
                role=role,
                cards=combo.cards,
                combo=combo.label,
                reason=decision.reason,
                remaining=sum(self.hands[seat].values()),
            ),
            combo,
        )

    def _emit(self, event: str, payload: dict[str, Any]) -> None:
        if self.event_handler is not None:
            self.event_handler(event, payload)

    def _is_valid_play(
        self,
        seat: int,
        cards: tuple[str, ...],
        combo: Combo | None,
        last_combo: Combo | None,
        can_pass: bool,
    ) -> bool:
        if not cards:
            return can_pass
        return (
            combo is not None
            and has_cards(self.hands[seat], cards)
            and can_beat(combo, last_combo)
        )

    def _view_for(self, seat: int, phase: str, **extra: Any) -> dict[str, Any]:
        history = self._history_view()
        view: dict[str, Any] = {
            "phase": phase,
            "seat": seat,
            "player_name": self.players[seat].name,
            "players": {index: player.name for index, player in enumerate(self.players)},
            "hand": counter_to_cards(self.hands[seat]),
            "hand_text": format_counter(self.hands[seat]),
            "hand_count": sum(self.hands[seat].values()),
            "bottom_count": len(self.bottom_cards),
            "played_cards": list(self.played_cards),
            "played_cards_text": format_cards(self.played_cards),
            "played_cards_by_player": self._played_cards_by_player(),
            "my_played_cards": self._played_cards_for(seat),
            "non_pass_counts": self._non_pass_counts(),
            "remaining_counts": {index: sum(hand.values()) for index, hand in enumerate(self.hands)},
            "bids": [record.__dict__ for record in self.bids],
            "history": history,
            "full_history": history,
            "recent_history": history[-12:],
        }
        if self.landlord is not None:
            view["landlord"] = self.landlord
            view["farmers"] = list(self.farmers)
            view["role"] = self._role_for(seat)
            view["role_by_player"] = {
                index: self._role_for(index)
                for index in range(3)
            }
            view["teammate"] = self._teammate_for(seat)
            view["opponents"] = self._opponents_for(seat)
            view["my_side"] = "landlord" if seat == self.landlord else "farmers"
            view["bottom_cards"] = list(self.bottom_cards)
            view["bottom_cards_text"] = format_cards(self.bottom_cards)
        if self.config.expose_all_hands:
            view["all_hands"] = {
                index: counter_to_cards(hand)
                for index, hand in enumerate(self.hands)
            }
        if "last_combo" in extra:
            combo = extra.pop("last_combo")
            view["last_combo"] = None if combo is None else {
                "kind": combo.kind,
                "label": combo.label,
                "cards": list(combo.cards),
                "primary_value": combo.primary_value,
                "main_length": combo.main_length,
            }
        view.update(extra)
        return view

    def _history_view(self) -> list[dict[str, Any]]:
        return [
            {
                "turn": record.turn,
                "player": record.player,
                "role": record.role,
                "cards": list(record.cards),
                "cards_text": format_cards(record.cards),
                "combo": record.combo,
                "reason": record.reason,
                "remaining": record.remaining,
                "is_pass": record.is_pass,
            }
            for record in self.plays
        ]

    def _played_cards_by_player(self) -> dict[int, list[str]]:
        return {
            seat: self._played_cards_for(seat)
            for seat in range(3)
        }

    def _played_cards_for(self, seat: int) -> list[str]:
        cards: list[str] = []
        for record in self.plays:
            if record.player == seat and not record.is_pass:
                cards.extend(record.cards)
        return cards

    def _non_pass_counts(self) -> dict[int, int]:
        counts = {seat: 0 for seat in range(3)}
        for record in self.plays:
            if not record.is_pass:
                counts[record.player] += 1
        return counts

    def _teammate_for(self, seat: int) -> int | None:
        if self.landlord is None or seat == self.landlord:
            return None
        for farmer in self.farmers:
            if farmer != seat:
                return farmer
        return None

    def _opponents_for(self, seat: int) -> list[int]:
        if self.landlord is None:
            return [index for index in range(3) if index != seat]
        if seat == self.landlord:
            return list(self.farmers)
        return [self.landlord]

    def _current_trick_view(
        self,
        last_combo: Combo | None,
        last_player: int | None,
        can_pass: bool,
    ) -> dict[str, Any]:
        if last_combo is None:
            return {
                "target_player": None,
                "target_combo": None,
                "target_cards": [],
                "can_pass": can_pass,
                "passes_after_target": 0,
            }
        return {
            "target_player": last_player,
            "target_combo": last_combo.label,
            "target_kind": last_combo.kind,
            "target_cards": list(last_combo.cards),
            "target_cards_text": format_cards(last_combo.cards),
            "can_pass": can_pass,
            "passes_after_target": self._passes_after_last_non_pass(),
        }

    def _passes_after_last_non_pass(self) -> int:
        count = 0
        for record in reversed(self.plays):
            if record.is_pass:
                count += 1
            else:
                break
        return count

    def _role_for(self, seat: int) -> str:
        if self.landlord is None:
            return "unknown"
        return "landlord" if seat == self.landlord else "farmer"

    def _result(self, winner: int, turns: int) -> GameResult:
        assert self.landlord is not None
        landlord_won = winner == self.landlord
        winner_side = "landlord" if landlord_won else "farmers"
        spring = self._spring_type(landlord_won)
        multiplier = 2 ** self.bomb_or_rocket_count
        if spring is not None:
            multiplier *= 2
        base = max(1, self.bid) * multiplier
        points = {seat: 0 for seat in range(3)}
        if landlord_won:
            points[self.landlord] = base * 2
            for farmer in self.farmers:
                points[farmer] = -base
        else:
            points[self.landlord] = -base * 2
            for farmer in self.farmers:
                points[farmer] = base

        return GameResult(
            winner=winner,
            winner_side=winner_side,
            landlord=self.landlord,
            farmers=self.farmers,
            bid=self.bid,
            multiplier=multiplier,
            spring=spring,
            points=points,
            turns=turns,
            bottom_cards=self.bottom_cards,
            bids=list(self.bids),
            plays=list(self.plays),
            initial_hands=self.initial_hands,
            redeals=self.redeals,
        )

    def _spring_type(self, landlord_won: bool) -> str | None:
        assert self.landlord is not None
        non_pass_counts = {seat: 0 for seat in range(3)}
        for play in self.plays:
            if not play.is_pass:
                non_pass_counts[play.player] += 1
        if landlord_won and all(non_pass_counts[farmer] == 0 for farmer in self.farmers):
            return "spring"
        if not landlord_won and non_pass_counts[self.landlord] == 1:
            return "anti-spring"
        return None


def run_match(
    players: list[Player],
    rounds: int,
    seed: int | None = None,
    expose_all_hands: bool = False,
) -> dict[str, Any]:
    rng = Random(seed)
    stats: dict[int, dict[str, Any]] = {
        player.seat: {
            "seat": player.seat,
            "name": player.name,
            "games": 0,
            "wins": 0,
            "landlord_games": 0,
            "landlord_wins": 0,
            "farmer_games": 0,
            "farmer_wins": 0,
            "points": 0,
        }
        for player in players
    }
    side_wins = defaultdict(int)
    results: list[GameResult] = []

    for _ in range(rounds):
        game_seed = rng.randrange(2**63)
        game = DouDizhuGame(players, GameConfig(seed=game_seed, expose_all_hands=expose_all_hands))
        result = game.play()
        results.append(result)
        side_wins[result.winner_side] += 1
        for player in players:
            record = stats[player.seat]
            record["games"] += 1
            record["points"] += result.points[player.seat]
            player_won = (
                (player.seat == result.landlord and result.winner_side == "landlord")
                or (player.seat != result.landlord and result.winner_side == "farmers")
            )
            if player_won:
                record["wins"] += 1
            if player.seat == result.landlord:
                record["landlord_games"] += 1
                if result.winner_side == "landlord":
                    record["landlord_wins"] += 1
            else:
                record["farmer_games"] += 1
                if result.winner_side == "farmers":
                    record["farmer_wins"] += 1

    return {
        "rounds": rounds,
        "seed": seed,
        "players": players,
        "stats": stats,
        "side_wins": dict(side_wins),
        "results": results,
    }


def result_summary(result: GameResult, players: list[Player]) -> str:
    winner = players[result.winner].name
    landlord = players[result.landlord].name
    farmers = ", ".join(players[seat].name for seat in result.farmers)
    return (
        f"Winner: {winner} ({result.winner_side}); "
        f"landlord={landlord}; farmers={farmers}; "
        f"bid={result.bid}; multiplier={result.multiplier}; spring={result.spring or '-'}; turns={result.turns}; "
        f"bottom={format_cards(result.bottom_cards)}"
    )


def _describe_exception(error: Exception) -> str:
    message = str(error).strip()
    if message:
        translations = {
            "model returned empty content": "模型返回了空内容",
            "模型连续返回空内容，已自动扩容重试但仍未得到正文": "模型连续返回空内容，已自动扩容重试但仍未得到正文",
        }
        return translations.get(message, message)
    return type(error).__name__
