from __future__ import annotations

import importlib
import json
import shlex
import subprocess
from random import Random
from typing import Any, Protocol

from .cards import RANK_VALUE, format_cards
from .combos import Combo
from .decision_types import BidDecision, PlayDecision
from .llm import create_llm_ai, is_llm_spec


class BaseAI(Protocol):
    name: str

    def choose_bid(self, view: dict[str, Any], valid_bids: list[int]) -> BidDecision | int:
        ...

    def choose_play(
        self,
        view: dict[str, Any],
        legal_plays: list[Combo],
        can_pass: bool,
    ) -> PlayDecision | list[str] | tuple[str, ...] | None:
        ...


class RandomAI:
    name = "random"

    def __init__(self, rng: Random | None = None) -> None:
        self.rng = rng or Random()

    def choose_bid(self, view: dict[str, Any], valid_bids: list[int]) -> BidDecision:
        bid = self.rng.choice(valid_bids)
        return BidDecision(bid, f"random bid {bid}")

    def choose_play(
        self,
        view: dict[str, Any],
        legal_plays: list[Combo],
        can_pass: bool,
    ) -> PlayDecision:
        choices: list[Combo | None] = list(legal_plays)
        if can_pass:
            choices.append(None)
        picked = self.rng.choice(choices)
        if picked is None:
            return PlayDecision((), "random pass")
        return PlayDecision(picked.cards, f"random {picked.label}")


class ConservativeAI:
    name = "conservative"

    def choose_bid(self, view: dict[str, Any], valid_bids: list[int]) -> BidDecision:
        strength = _hand_strength(view["hand"])
        desired = 0
        if strength >= 34:
            desired = 2
        elif strength >= 27:
            desired = 1
        bid = max([bid for bid in valid_bids if bid <= desired], default=0)
        return BidDecision(bid, f"strength={strength:.1f}, cautious")

    def choose_play(
        self,
        view: dict[str, Any],
        legal_plays: list[Combo],
        can_pass: bool,
    ) -> PlayDecision:
        non_bombs = [play for play in legal_plays if play.kind not in {"bomb", "rocket"}]
        if can_pass and not non_bombs:
            return PlayDecision((), "avoid spending bomb")
        picked = min(non_bombs or legal_plays, key=lambda combo: (combo.size, combo.primary_value))
        return PlayDecision(picked.cards, f"lowest safe {picked.label}")


class GreedyAI:
    name = "greedy"

    def choose_bid(self, view: dict[str, Any], valid_bids: list[int]) -> BidDecision:
        strength = _hand_strength(view["hand"])
        desired = 0
        if strength >= 42:
            desired = 3
        elif strength >= 33:
            desired = 2
        elif strength >= 24:
            desired = 1
        bid = max([bid for bid in valid_bids if bid <= desired], default=0)
        return BidDecision(bid, f"strength={strength:.1f}, aggressive")

    def choose_play(
        self,
        view: dict[str, Any],
        legal_plays: list[Combo],
        can_pass: bool,
    ) -> PlayDecision:
        if can_pass:
            non_bombs = [play for play in legal_plays if play.kind not in {"bomb", "rocket"}]
            if non_bombs:
                picked = min(non_bombs, key=lambda combo: (combo.primary_value, combo.size))
                return PlayDecision(picked.cards, f"smallest winning {picked.label}")
            if legal_plays and _opponent_near_out(view):
                picked = min(legal_plays, key=lambda combo: (combo.kind == "rocket", combo.primary_value))
                return PlayDecision(picked.cards, f"block near-out with {picked.label}")
            return PlayDecision((), "save bomb")

        picked = max(
            legal_plays,
            key=lambda combo: (
                combo.size,
                combo.kind in {"straight", "pair_straight", "triple_straight", "airplane_single", "airplane_pair"},
                -combo.primary_value,
            ),
        )
        return PlayDecision(picked.cards, f"largest lead {picked.label}")


class ExternalProcessAI:
    """Runs one command per decision using a simple JSON-in/JSON-out contract."""

    def __init__(self, command: str, name: str | None = None, timeout_seconds: float = 20.0) -> None:
        self.command = command
        self.name = name or f"process:{command}"
        self.timeout_seconds = timeout_seconds

    def choose_bid(self, view: dict[str, Any], valid_bids: list[int]) -> BidDecision:
        payload = {"type": "bid", "view": view, "valid_bids": valid_bids}
        data = self._call(payload)
        return BidDecision(int(data.get("bid", 0)), str(data.get("reason", "")))

    def choose_play(
        self,
        view: dict[str, Any],
        legal_plays: list[Combo],
        can_pass: bool,
    ) -> PlayDecision:
        payload = {
            "type": "play",
            "view": view,
            "legal_plays": [_combo_to_json(combo) for combo in legal_plays],
            "can_pass": can_pass,
        }
        data = self._call(payload)
        return PlayDecision(tuple(data.get("cards", [])), str(data.get("reason", "")))

    def _call(self, payload: dict[str, Any]) -> dict[str, Any]:
        completed = subprocess.run(
            shlex.split(self.command),
            input=json.dumps(payload, ensure_ascii=False),
            text=True,
            capture_output=True,
            timeout=self.timeout_seconds,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or f"external AI failed: {self.command}")
        return json.loads(completed.stdout)


def create_ai(spec: str, rng: Random | None = None) -> BaseAI:
    normalized = spec.strip()
    if normalized == "random":
        return RandomAI(rng)
    if normalized == "greedy":
        return GreedyAI()
    if normalized == "conservative":
        return ConservativeAI()
    if is_llm_spec(normalized):
        return create_llm_ai(normalized)
    if normalized.startswith("process:"):
        return ExternalProcessAI(normalized.removeprefix("process:"))
    if ":" in normalized:
        module_name, class_name = normalized.split(":", 1)
        module = importlib.import_module(module_name)
        cls = getattr(module, class_name)
        try:
            return cls(rng=rng)
        except TypeError:
            return cls()
    raise ValueError(f"unknown AI spec: {spec}")


def built_in_ai_names() -> list[str]:
    return [
        "random",
        "greedy",
        "conservative",
        "openai",
        "deepseek",
        "gemini",
        "deepseek@deepseek-v4-pro",
        "ollama@qwen3:8b",
        "openrouter@provider/model",
        "qwen@qwen-plus",
        "bedrock@anthropic.claude-3-5-sonnet-20241022-v2:0",
    ]


def normalize_bid_decision(decision: BidDecision | int, valid_bids: list[int]) -> BidDecision:
    if isinstance(decision, BidDecision):
        bid = decision.bid
        reason = decision.reason
    else:
        bid = int(decision)
        reason = ""
    if bid not in valid_bids:
        safe_bid = 0 if 0 in valid_bids else valid_bids[0]
        return BidDecision(safe_bid, f"invalid bid {bid}; coerced to {safe_bid}")
    return BidDecision(bid, reason)


def normalize_play_decision(
    decision: PlayDecision | list[str] | tuple[str, ...] | None,
) -> PlayDecision:
    if decision is None:
        return PlayDecision(())
    if isinstance(decision, PlayDecision):
        return decision
    return PlayDecision(tuple(decision))


def _combo_to_json(combo: Combo) -> dict[str, Any]:
    return {
        "kind": combo.kind,
        "label": combo.label,
        "cards": list(combo.cards),
        "primary_value": combo.primary_value,
        "main_length": combo.main_length,
        "display": combo.display(),
    }


def _hand_strength(cards: list[str]) -> float:
    high_card_score = sum(max(0, RANK_VALUE[card] - RANK_VALUE["10"]) for card in cards)
    counts = {card: cards.count(card) for card in set(cards)}
    bomb_score = sum(10 for count in counts.values() if count == 4)
    rocket_score = 12 if "BJ" in counts and "RJ" in counts else 0
    pair_triple_score = sum(1.5 for count in counts.values() if count == 2) + sum(3 for count in counts.values() if count == 3)
    return high_card_score + bomb_score + rocket_score + pair_triple_score


def _opponent_near_out(view: dict[str, Any]) -> bool:
    my_seat = view["seat"]
    remaining = view.get("remaining_counts", {})
    return any(int(count) <= 2 for seat, count in remaining.items() if int(seat) != my_seat)


def describe_play(cards: tuple[str, ...]) -> str:
    return "pass" if not cards else format_cards(cards)
