"""Leak-free, rotation-invariant features and hierarchical replay targets."""

from __future__ import annotations

from typing import Iterable

from replay_data import RANKS, STREETS, POSITIONS, action_bucket


FAMILY_ACTIONS = ("fold", "check", "call", "raise", "allin")
SIZE_ACTIONS = ("0.33", "0.50", "0.75", "1.00", "1.50", "2.00")
INPUT_SIZE_V2 = 232
FAMILY_OUTPUT_SIZE = len(FAMILY_ACTIONS)
SIZE_OUTPUT_SIZE = len(SIZE_ACTIONS)


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


def hierarchical_target(decision: dict) -> tuple[int, int]:
    """Return (action family, raise size), with -1 size outside ordinary raises."""
    action_index = decision.get("action_index")
    if action_index is None:
        action_index = action_bucket(decision)[0]
    action_index = int(action_index)
    if action_index <= 2:
        return action_index, -1
    if action_index == 9:
        return FAMILY_ACTIONS.index("allin"), -1
    if 3 <= action_index <= 8:
        return FAMILY_ACTIONS.index("raise"), action_index - 3
    raise ValueError(f"invalid flat action index: {action_index}")


def legal_family_mask(decision: dict) -> list[bool]:
    legal = set(decision.get("legal", []))
    return [
        "fold" in legal,
        "check" in legal,
        "call" in legal,
        "raise" in legal or "bet" in legal,
        "allin" in legal,
    ]


def decision_features_v2(decision: dict) -> list[float]:
    """Encode public state without account, outcome, or absolute-seat leakage."""
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
    can_raise_value = decision.get("can_raise")
    if can_raise_value is None:
        can_raise_value = "raise" in decision.get("legal", []) or "bet" in decision.get("legal", [])
    players = list(decision.get("players", []))
    active_players = [item for item in players if item.get("state") in ("in", "allin")]
    opponent_stacks = [max(0, int(item.get("stack", 0))) for item in active_players if item.get("seat") != decision.get("seat")]
    effective = min(stack, max(opponent_stacks, default=stack))
    active = len(active_players)
    all_in = sum(item.get("state") == "allin" for item in players)
    folded = sum(item.get("state") == "folded" for item in players)
    features.extend([
        _clamp(pot / 60_000), _clamp(pot / 10_000), _clamp(stack / 10_000),
        _clamp(to_call / 10_000), _clamp(me_bet / 10_000), _clamp(invested / 10_000),
        _clamp(minimum / 10_000), _clamp(maximum / 10_000),
        _clamp(to_call / max(1, pot + to_call)), _clamp(stack / max(1, pot) / 20),
        _clamp(effective / 10_000), _clamp(effective / max(1, pot) / 20),
        _clamp(active / 6), _clamp(all_in / 6), _clamp(folded / 6),
        float(bool(can_raise_value)),
    ])

    # Physical seat numbers are arbitrary.  Arrange all players relative to
    # the decision maker so a whole-table rotation produces identical input.
    hero_seat = int(decision.get("seat", 0))
    by_relative = {(int(item.get("seat", 0)) - hero_seat) % 6: item for item in players}
    for relative in range(6):
        item = by_relative.get(relative, {})
        state = item.get("state")
        features.extend([
            _clamp(int(item.get("stack", 0)) / 10_000),
            _clamp(int(item.get("bet", 0)) / 10_000),
            _clamp(int(item.get("invested", 0)) / 10_000),
            float(state == "in"), float(state == "folded"), float(state == "allin"),
        ])

    counts = {(name, action): 0 for name in STREETS for action in ("fold", "check", "call", "aggressive")}
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

    # Preserve the recent action order.  Left padding keeps the newest action
    # at a stable slot while remaining independent of account identifiers.
    recent = history[-6:]
    recent = [None] * (6 - len(recent)) + recent
    for item in recent:
        if item is None:
            features.extend([0.0] * 17)
            continue
        actor = (int(item.get("seat", hero_seat)) - hero_seat) % 6
        action = item.get("type")
        features.append(1.0)
        features.extend(1.0 if item.get("street") == value else 0.0 for value in STREETS)
        features.extend(1.0 if actor == value else 0.0 for value in range(6))
        features.extend([
            float(action == "fold"), float(action == "check"), float(action == "call"),
            float(action in ("bet", "raise", "allin")),
            _clamp(int(item.get("amount", 0)) / max(1, pot)),
            _clamp(int(item.get("to", 0)) / 10_000),
        ])

    features.extend(float(value) for value in legal_family_mask(decision))
    if len(features) > INPUT_SIZE_V2:
        raise AssertionError(f"v2 feature count {len(features)} exceeds {INPUT_SIZE_V2}")
    features.extend([0.0] * (INPUT_SIZE_V2 - len(features)))
    return features
