"""Feature and action encoding for public-replay behavior cloning."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable


RANKS = "23456789TJQKA"
STREETS = ("preflop", "flop", "turn", "river")
POSITIONS = ("BTN", "SB", "BB", "UTG", "HJ", "CO")
RAISE_FRACTIONS = (0.33, 0.50, 0.75, 1.00, 1.50, 2.00)
ACTIONS = (
    "fold", "check", "call",
    "raise_0.33", "raise_0.50", "raise_0.75",
    "raise_1.00", "raise_1.50", "raise_2.00", "allin",
)
INPUT_SIZE = 104
OUTPUT_SIZE = len(ACTIONS)


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def _canonical_suits(cards: Iterable[str]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for card in cards:
        if card and len(card) == 2 and card[1] not in mapping:
            mapping[card[1]] = len(mapping)
    return mapping


def _card_features(card: str | None, suits: dict[str, int]) -> list[float]:
    if not card:
        return [0.0] * 6
    rank = RANKS.index(card[0]) + 2
    suit = suits[card[1]]
    return [1.0, rank / 14.0, *(1.0 if suit == index else 0.0 for index in range(4))]


def action_bucket(decision: dict) -> tuple[int, dict]:
    """Project an applied platform action into the fixed 10-action space."""
    action = decision.get("action", {})
    kind = action.get("type")
    if kind in ("fold", "check", "call"):
        if kind == "call" and int(decision.get("stack", 0)) <= int(decision.get("to_call", 0)):
            return ACTIONS.index("allin"), {"bucket": "allin", "fraction": None, "error": 0.0}
        return ACTIONS.index(kind), {"bucket": kind, "fraction": None, "error": 0.0}
    if kind == "allin":
        return ACTIONS.index("allin"), {"bucket": "allin", "fraction": None, "error": 0.0}
    if kind != "raise":
        raise ValueError(f"unsupported replay action: {kind!r}")
    target = int(action.get("to", 0))
    maximum = int(decision.get("max_raise_to", 0))
    if maximum > 0 and target >= maximum:
        return ACTIONS.index("allin"), {"bucket": "allin", "fraction": None, "error": 0.0}
    contribution = max(0, target - int(decision.get("me_bet", 0)))
    denominator = max(1, int(decision.get("pot", 0)) + int(decision.get("to_call", 0)))
    fraction = contribution / denominator
    nearest = min(range(len(RAISE_FRACTIONS)), key=lambda index: abs(RAISE_FRACTIONS[index] - fraction))
    bucket = f"raise_{RAISE_FRACTIONS[nearest]:.2f}"
    return 3 + nearest, {
        "bucket": bucket,
        "fraction": round(fraction, 6),
        "error": round(abs(RAISE_FRACTIONS[nearest] - fraction), 6),
    }


def decision_features(decision: dict) -> list[float]:
    """Encode a decision without account identity or outcome leakage."""
    hole = list(decision.get("hole", []))
    board = list(decision.get("board", []))
    cards = (hole + board)[:7]
    suits = _canonical_suits(cards)
    features: list[float] = []
    for index in range(7):
        features.extend(_card_features(cards[index] if index < len(cards) else None, suits))

    street = decision.get("street")
    position = decision.get("position")
    features.extend(1.0 if street == value else 0.0 for value in STREETS)
    features.extend(1.0 if position == value else 0.0 for value in POSITIONS)

    pot = max(0, int(decision.get("pot", 0)))
    stack = max(0, int(decision.get("stack", 0)))
    to_call = max(0, int(decision.get("to_call", 0)))
    me_bet = max(0, int(decision.get("me_bet", 0)))
    invested = max(0, int(decision.get("invested", 0)))
    minimum = max(0, int(decision.get("min_raise_to", 0)))
    maximum = max(0, int(decision.get("max_raise_to", 0)))
    players = list(decision.get("players", []))
    active = sum(item.get("state") in ("in", "allin") for item in players)
    features.extend([
        _clamp(pot / 60_000), _clamp(stack / 10_000), _clamp(to_call / 10_000),
        _clamp(me_bet / 10_000), _clamp(invested / 10_000),
        _clamp(minimum / 10_000), _clamp(maximum / 10_000),
        _clamp(to_call / max(1, pot + to_call)), _clamp(stack / max(1, pot) / 20),
        float(bool(decision.get("can_raise"))), float(to_call == 0),
        _clamp((active - 1) / 5), _clamp(int(decision.get("seat", 0)) / 5),
        _clamp(int(decision.get("button", 0)) / 5),
    ])

    counts = {(street_name, action): 0 for street_name in STREETS for action in ("fold", "check", "call", "aggressive")}
    history = list(decision.get("history", []))
    for item in history:
        action = item.get("type")
        group = "aggressive" if action in ("bet", "raise", "allin") else action
        key = (item.get("street"), group)
        if key in counts:
            counts[key] += 1
    for street_name in STREETS:
        for action in ("fold", "check", "call", "aggressive"):
            features.append(_clamp(counts[(street_name, action)] / 6))

    last = history[-1] if history else {}
    last_type = last.get("type")
    features.extend([
        float(last_type == "fold"), float(last_type == "check"), float(last_type == "call"),
        float(last_type in ("bet", "raise", "allin")),
        _clamp(int(last.get("amount", 0)) / max(1, pot)),
    ])
    legal = set(decision.get("legal", []))
    features.extend([
        float("fold" in legal), float("check" in legal), float("call" in legal),
        float("raise" in legal or "bet" in legal), float("allin" in legal),
    ])
    if len(features) > INPUT_SIZE:
        raise AssertionError(f"feature count {len(features)} exceeds {INPUT_SIZE}")
    features.extend([0.0] * (INPUT_SIZE - len(features)))
    return features


def load_jsonl(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]

