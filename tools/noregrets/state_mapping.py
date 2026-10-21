#!/usr/bin/env python3
"""Map an AGX decision snapshot to the pinned NoRegrets public abstraction.

This module mirrors commit 757f769's public-state and ``pluribus`` action
menu semantics.  It does not load a blueprint or invent teacher values.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field
from typing import Any


PLAYERS = 6
STARTING_STACK = 10_000
SB = 50
BB = 100
RANKS = "23456789TJQKA"
SUITS = "cdhs"
STREETS = ("preflop", "flop", "turn", "river")
POSITIONS = ("BTN", "SB", "BB", "UTG", "HJ", "CO")
BET_SIZES = (25, 33, 50, 75, 100, 150, 200, 300)
TOKEN_FOLD = 0
TOKEN_CHECK_CALL = 1
TOKEN_ALLIN = 2
TOKEN_STREET_SEP = 15
SUIT_PERMS = tuple(itertools.permutations(range(4)))


class MappingError(ValueError):
    pass


def card_id(card: str) -> int:
    if not isinstance(card, str) or len(card) != 2:
        raise MappingError(f"invalid card: {card!r}")
    try:
        return RANKS.index(card[0].upper()) * 4 + SUITS.index(card[1].lower())
    except ValueError as exc:
        raise MappingError(f"invalid card: {card!r}") from exc


def card_str(value: int) -> str:
    if not 0 <= value < 52:
        raise MappingError(f"invalid card id: {value}")
    return RANKS[value >> 2] + SUITS[value & 3]


def canonicalize_cards(hole: list[str], board: list[str]) -> dict[str, Any]:
    if len(hole) != 2 or len(board) not in (0, 3, 4, 5):
        raise MappingError("hole/board card counts are invalid")
    raw_hole = [card_id(card) for card in hole]
    raw_board = [card_id(card) for card in board]
    if len(set(raw_hole + raw_board)) != len(raw_hole) + len(raw_board):
        raise MappingError("duplicate visible card")
    best: tuple[int, tuple[int, ...], list[int], list[int]] | None = None
    for perm_tuple in SUIT_PERMS:
        mapped_hole = [(card & ~3) | perm_tuple[card & 3] for card in raw_hole]
        mapped_board = [(card & ~3) | perm_tuple[card & 3] for card in raw_board]
        key = len(raw_board)
        for value in sorted(mapped_hole) + sorted(mapped_board):
            key = (key << 6) | value
        candidate = (key, perm_tuple, mapped_hole, mapped_board)
        if best is None or candidate[0] < best[0]:
            best = candidate
    assert best is not None
    key, perm_tuple, mapped_hole, mapped_board = best
    inverse = [0] * 4
    for source, target in enumerate(perm_tuple):
        inverse[target] = source
    return {
        "hole": [card_str(card) for card in mapped_hole],
        "board": [card_str(card) for card in mapped_board],
        "key": key,
        "suit_permutation": list(perm_tuple),
        "inverse_suit_permutation": inverse,
    }


def restore_cards(cards: list[str], inverse: list[int]) -> list[str]:
    return [card_str((card_id(card) & ~3) | inverse[card_id(card) & 3]) for card in cards]


def bet_menu(street: str, raises: int) -> tuple[int, ...]:
    if street == "preflop":
        if raises == 0:
            return (1, 2, 3, 4)
        if raises == 1:
            return (2, 4, 6)
        if raises == 2:
            return (4, 6)
        return ()
    if raises == 0:
        return (2, 4)
    if raises == 1:
        return (4,)
    return ()


@dataclass
class PublicState:
    button: int
    street: str = "preflop"
    stacks: list[int] = field(default_factory=lambda: [STARTING_STACK] * PLAYERS)
    bets: list[int] = field(default_factory=lambda: [0] * PLAYERS)
    invested: list[int] = field(default_factory=lambda: [0] * PLAYERS)
    folded: list[bool] = field(default_factory=lambda: [False] * PLAYERS)
    allin: list[bool] = field(default_factory=lambda: [False] * PLAYERS)
    acted: list[bool] = field(default_factory=lambda: [False] * PLAYERS)
    current_bet: int = BB
    min_raise_inc: int = BB
    raises: int = 0

    @classmethod
    def initial(cls, button: int) -> "PublicState":
        state = cls(button=button)
        state.commit((button + 1) % PLAYERS, SB)
        state.commit((button + 2) % PLAYERS, BB)
        return state

    @property
    def pot(self) -> int:
        return sum(self.invested)

    def commit(self, seat: int, amount: int) -> None:
        paid = max(0, min(self.stacks[seat], int(amount)))
        self.stacks[seat] -= paid
        self.bets[seat] += paid
        self.invested[seat] += paid
        self.allin[seat] = self.stacks[seat] == 0

    def begin_street(self, street: str) -> None:
        if STREETS.index(street) != STREETS.index(self.street) + 1:
            raise MappingError(f"non-consecutive street transition: {self.street} -> {street}")
        self.street = street
        self.bets = [0] * PLAYERS
        self.current_bet = 0
        self.min_raise_inc = BB
        self.raises = 0
        self.acted = [False] * PLAYERS

    def bounds(self, seat: int) -> tuple[int, int] | None:
        maximum = self.bets[seat] + self.stacks[seat]
        if maximum <= self.current_bet:
            return None
        if self.acted[seat] and self.current_bet - self.bets[seat] < self.min_raise_inc:
            return None
        return min(self.current_bet + self.min_raise_inc, maximum), maximum

    def targets(self, seat: int) -> list[dict[str, Any]]:
        bounds = self.bounds(seat)
        if bounds is None:
            return []
        low, high = bounds
        to_call = max(0, self.current_bet - self.bets[seat])
        seen: set[int] = set()
        targets = []
        for index in bet_menu(self.street, self.raises):
            target = self.current_bet + (self.pot + to_call) * BET_SIZES[index] // 100
            target = max(low, min(high, target))
            if target < high and target not in seen:
                seen.add(target)
                targets.append({"kind": "bet", "size_index": index, "percent": BET_SIZES[index], "to": target, "token": 3 + index})
        targets.append({"kind": "allin", "to": high, "token": TOKEN_ALLIN})
        return targets

    def apply(self, seat: int, kind: str, target: int | None = None) -> None:
        to_call = max(0, self.current_bet - self.bets[seat])
        if kind == "fold":
            if to_call > 0:
                self.folded[seat] = True
            self.acted[seat] = True
            return
        if kind in ("check", "call"):
            self.commit(seat, to_call)
            self.acted[seat] = True
            return
        if kind not in ("raise", "bet", "allin"):
            raise MappingError(f"unsupported history action: {kind!r}")
        maximum = self.bets[seat] + self.stacks[seat]
        wanted = maximum if kind == "allin" and target is None else int(target or 0)
        if wanted <= self.current_bet:
            self.commit(seat, to_call)
            self.acted[seat] = True
            return
        if wanted > maximum or wanted <= self.bets[seat]:
            raise MappingError(f"invalid raise target {wanted} for seat {seat}")
        before = self.current_bet
        self.commit(seat, wanted - self.bets[seat])
        increase = wanted - before
        if increase >= self.min_raise_inc:
            self.min_raise_inc = increase
            for other in range(PLAYERS):
                if other != seat:
                    self.acted[other] = False
        self.current_bet = wanted
        self.raises += 1
        self.acted[seat] = True


def normalized_seats(button: int) -> tuple[dict[int, int], dict[int, int]]:
    forward = {seat: (seat - button) % PLAYERS for seat in range(PLAYERS)}
    inverse = {normalized: seat for seat, normalized in forward.items()}
    return forward, inverse


def _nearest_target(target: int, choices: list[dict[str, Any]]) -> tuple[dict[str, Any], float]:
    if not choices:
        raise MappingError("raise cannot be represented because NoRegrets has no legal raise")
    choice = min(choices, key=lambda item: abs(math.log(max(1, target)) - math.log(max(1, item["to"]))))
    error = abs(math.log(max(1, target)) - math.log(max(1, choice["to"])))
    return choice, error


def _advance_to(state: PublicState, street: str, tokens: list[int] | None = None) -> None:
    while state.street != street:
        state.begin_street(STREETS[STREETS.index(state.street) + 1])
        if tokens is not None:
            tokens.append(TOKEN_STREET_SEP)


def _legal_families(decision: dict[str, Any], state: PublicState, seat: int) -> tuple[list[str], list[str]]:
    legal = set(decision.get("legal", []))
    agx = []
    for family in ("fold", "check", "call"):
        if family in legal:
            agx.append(family)
    if "raise" in legal or "bet" in legal:
        agx.append("raise")
    # A short all-in call is represented by NoRegrets CheckCall, not by its
    # raising AllIn abstraction, so do not count that alias as a new family.
    if "allin" in legal and int(decision.get("max_raise_to", 0)) > state.current_bet:
        agx.append("allin")
    to_call = max(0, state.current_bet - state.bets[seat])
    noregrets = ["check" if to_call == 0 else "fold", "call" if to_call else "check"]
    noregrets = list(dict.fromkeys(noregrets))
    targets = state.targets(seat)
    if any(item["kind"] == "bet" for item in targets):
        noregrets.append("raise")
    if targets:
        noregrets.append("allin")
    return agx, noregrets


def map_decision(decision: dict[str, Any]) -> dict[str, Any]:
    required = ("seat", "button", "hole", "board", "street", "players", "history")
    missing = [name for name in required if name not in decision]
    if missing:
        raise MappingError(f"missing fields: {', '.join(missing)}")
    button = int(decision["button"])
    hero = int(decision["seat"])
    street = str(decision["street"])
    if not 0 <= button < PLAYERS or not 0 <= hero < PLAYERS or street not in STREETS:
        raise MappingError("invalid button, hero seat or street")
    players = sorted(decision["players"], key=lambda item: int(item["seat"]))
    if len(players) != PLAYERS or [int(item["seat"]) for item in players] != list(range(PLAYERS)):
        raise MappingError("players must contain seats 0..5")

    real = PublicState.initial(button)
    shadow = PublicState.initial(button)
    tokens: list[int] = []
    projection_events = []
    reasons: list[str] = []
    for index, action in enumerate(decision["history"]):
        action_street = str(action.get("street"))
        _advance_to(real, action_street)
        _advance_to(shadow, action_street, tokens)
        seat = int(action["seat"])
        kind = str(action.get("type"))
        target = action.get("to")
        if kind in ("fold", "check", "call"):
            token = TOKEN_FOLD if kind == "fold" and real.current_bet > real.bets[seat] else TOKEN_CHECK_CALL
            shadow_kind = "fold" if token == TOKEN_FOLD else "call"
        else:
            actual_target = int(target) if target is not None else real.bets[seat] + real.stacks[seat]
            choices = shadow.targets(seat)
            if not choices:
                # Mirrors Table::map_concrete: a real raise degrades to
                # CheckCall when the abstract shadow has no legal raise.
                reasons.append("history_raise_without_noregrets_raise")
                token = TOKEN_CHECK_CALL
                shadow_kind = "call"
                projected_to = shadow.bets[seat] + max(0, shadow.current_bet - shadow.bets[seat])
                log_error = abs(math.log(max(1, actual_target)) - math.log(max(1, projected_to)))
            else:
                choice, log_error = _nearest_target(actual_target, choices)
                token = int(choice["token"])
                shadow_kind = "allin" if choice["kind"] == "allin" else "raise"
                projected_to = int(choice["to"])
            target = actual_target
            projection_events.append({
                "history_index": index,
                "street": action_street,
                "actual_to": actual_target,
                "projected_to": projected_to,
                "error_chips": abs(actual_target - projected_to),
                "error_log": round(log_error, 9),
                "token": token,
            })
            shadow.apply(seat, shadow_kind, projected_to if shadow_kind in ("raise", "allin") else None)
        tokens.append(token)
        real.apply(seat, kind, int(target) if target is not None else None)
        if kind in ("fold", "check", "call"):
            shadow.apply(seat, shadow_kind)
        if real.allin[seat] != shadow.allin[seat]:
            reasons.append("shadow_structural_divergence")

    _advance_to(real, street)
    _advance_to(shadow, street, tokens)
    expected = {
        "pot": real.pot,
        "stack": real.stacks[hero],
        "me_bet": real.bets[hero],
        "invested": real.invested[hero],
        "to_call": max(0, real.current_bet - real.bets[hero]),
    }
    for field_name, reconstructed in expected.items():
        if int(decision.get(field_name, reconstructed)) != reconstructed:
            reasons.append(f"snapshot_mismatch:{field_name}")
    for item in players:
        seat = int(item["seat"])
        state_name = "folded" if real.folded[seat] else ("allin" if real.allin[seat] else "in")
        if (int(item["stack"]), int(item["bet"]), int(item["invested"]), item["state"]) != (
            real.stacks[seat], real.bets[seat], real.invested[seat], state_name
        ):
            reasons.append(f"snapshot_mismatch:player_{seat}")

    legal = set(decision.get("legal", []))
    agx_can_raise = bool(decision["can_raise"]) if "can_raise" in decision else bool({"raise", "bet"} & legal)
    nr_can_raise = shadow.bounds(hero) is not None
    if agx_can_raise != nr_can_raise:
        reasons.append("real_shadow_raise_legality_divergence")
    agx_legal, nr_legal = _legal_families(decision, shadow, hero)
    legal_match = set(agx_legal) == set(nr_legal)
    projection_nonzero = any(event["error_chips"] for event in projection_events)
    unsupported = bool(reasons)
    quality = "unsupported" if unsupported else ("projected" if projection_nonzero or not legal_match else "exact")

    forward, inverse = normalized_seats(button)
    canonical = canonicalize_cards(list(decision["hole"]), list(decision["board"]))
    normalized_players = []
    for item in players:
        old_seat = int(item["seat"])
        normalized_players.append({
            "seat": forward[old_seat],
            "stack": int(item["stack"]),
            "bet": int(item["bet"]),
            "invested": int(item["invested"]),
            "state": item["state"],
        })
    normalized_players.sort(key=lambda item: item["seat"])
    return {
        "schema": "agx.noregrets-state.v1",
        "mapping_quality": quality,
        "unsupported_reasons": sorted(set(reasons)),
        "source": {"match_id": decision.get("match_id"), "hand": decision.get("hand")},
        "hero_seat": forward[hero],
        "button": 0,
        "seat_map": {str(key): value for key, value in forward.items()},
        "inverse_seat_map": {str(key): value for key, value in inverse.items()},
        "street": street,
        "hole": canonical["hole"],
        "board": canonical["board"],
        "card_key": canonical["key"],
        "suit_permutation": canonical["suit_permutation"],
        "inverse_suit_permutation": canonical["inverse_suit_permutation"],
        "pot": shadow.pot,
        "players": normalized_players,
        "history_tokens": tokens,
        "raises_this_street": shadow.raises,
        "legal_families_agx": agx_legal,
        "legal_families_noregrets": nr_legal,
        "legal_families_match": legal_match,
        "action_menu": shadow.targets(hero),
        "projection": {
            "events": projection_events,
            "max_error_chips": max((event["error_chips"] for event in projection_events), default=0),
            "max_error_log": max((event["error_log"] for event in projection_events), default=0.0),
        },
    }


def roundtrip_public(mapped: dict[str, Any]) -> dict[str, Any]:
    inverse_seats = {int(key): int(value) for key, value in mapped["inverse_seat_map"].items()}
    players = []
    for item in mapped["players"]:
        restored = dict(item)
        restored["seat"] = inverse_seats[int(item["seat"])]
        players.append(restored)
    players.sort(key=lambda item: item["seat"])
    inverse_suits = list(mapped["inverse_suit_permutation"])
    return {
        "seat": inverse_seats[int(mapped["hero_seat"])],
        "button": inverse_seats[int(mapped["button"])],
        "hole": restore_cards(list(mapped["hole"]), inverse_suits),
        "board": restore_cards(list(mapped["board"]), inverse_suits),
        "players": players,
    }
