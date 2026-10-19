#!/usr/bin/env python3
"""Deterministic six-player NLHE engine for rules 4.1 / simulation 4.0."""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
from typing import Optional


RULES_VERSION = "rsi-poker-4.1"
SIMULATION_VERSION = "rsi-poker-4.0"
PLAYERS = 6
STARTING_STACK = 10_000
SB = 50
BB = 100
STREETS = ("preflop", "flop", "turn", "river")
POSITIONS = ("BTN", "SB", "BB", "UTG", "HJ", "CO")
RANKS = "23456789TJQKA"
SUITS = "cdhs"


def evaluate_five(cards: list[str]) -> tuple[int, ...]:
    values = sorted((RANKS.index(card[0]) + 2 for card in cards), reverse=True)
    counts = {value: values.count(value) for value in set(values)}
    groups = sorted(((count, value) for value, count in counts.items()), reverse=True)
    flush = len({card[1] for card in cards}) == 1
    unique = sorted(set(values), reverse=True)
    if 14 in unique:
        unique.append(1)
    straight_high = max(
        (unique[i] for i in range(len(unique) - 4) if unique[i] - unique[i + 4] == 4),
        default=0,
    )
    if flush and straight_high:
        return (8, straight_high)
    if groups[0][0] == 4:
        return (7, groups[0][1], groups[1][1])
    trips = sorted((value for value, count in counts.items() if count == 3), reverse=True)
    full_house_pairs = sorted(
        (value for value, count in counts.items() if count >= 2 and (not trips or value != trips[0])),
        reverse=True,
    )
    if trips and full_house_pairs:
        return (6, trips[0], full_house_pairs[0])
    if flush:
        return (5, *values)
    if straight_high:
        return (4, straight_high)
    if trips:
        return (3, trips[0], *(value for value in values if value != trips[0]))
    pairs = sorted((value for value, count in counts.items() if count == 2), reverse=True)
    singles = sorted((value for value, count in counts.items() if count == 1), reverse=True)
    if len(pairs) >= 2:
        return (2, pairs[0], pairs[1], singles[0])
    if len(pairs) == 1:
        return (1, pairs[0], *singles)
    return (0, *values)


def evaluate(cards: list[str]) -> tuple[int, ...]:
    if len(cards) < 5:
        raise ValueError("牌型评估至少需要5张牌")
    return max(evaluate_five(list(choice)) for choice in combinations(cards, 5))


@dataclass
class Seat:
    seat: int
    player: str
    hole: list[str]
    stack: int = STARTING_STACK
    street_bet: int = 0
    invested: int = 0
    folded: bool = False
    all_in: bool = False
    has_acted: bool = False
    acted_facing_bet: int = 0
    acted_on_wager: bool = False

    def can_act(self) -> bool:
        return not self.folded and not self.all_in and self.stack > 0


@dataclass
class PokerHand:
    button: int
    holes: list[list[str]]
    players: Optional[list[str]] = None
    starting_stacks: Optional[list[int]] = None
    board: list[str] = field(default_factory=list)
    street_index: int = 0
    seats: list[Seat] = field(init=False)
    current_bet: int = 0
    last_full_raise: int = BB
    pending: set[int] = field(default_factory=set)
    cursor: int = 0
    history: list[dict] = field(default_factory=list)
    settled: bool = False
    refunds: list[dict] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not 0 <= self.button < PLAYERS or len(self.holes) != PLAYERS:
            raise ValueError("必须提供六个座位和合法按钮位")
        names = self.players or [f"p{i}" for i in range(PLAYERS)]
        stacks = self.starting_stacks or [STARTING_STACK] * PLAYERS
        if len(names) != PLAYERS or len(stacks) != PLAYERS:
            raise ValueError("玩家和筹码数组长度必须为6")
        cards = [card for hole in self.holes for card in hole]
        if any(len(hole) != 2 for hole in self.holes) or len(cards) != len(set(cards)):
            raise ValueError("底牌缺失或重复")
        if any(card[0] not in RANKS or card[1] not in SUITS for card in cards):
            raise ValueError("底牌编码无效")
        self.seats = [Seat(i, names[i], list(self.holes[i]), stacks[i]) for i in range(PLAYERS)]
        self._commit((self.button + 1) % PLAYERS, min(SB, stacks[(self.button + 1) % PLAYERS]))
        self._commit((self.button + 2) % PLAYERS, min(BB, stacks[(self.button + 2) % PLAYERS]))
        self.current_bet = max(seat.street_bet for seat in self.seats)
        self.pending = {seat.seat for seat in self.seats if seat.can_act()}
        self.cursor = (self.button + 3) % PLAYERS

    @property
    def street(self) -> str:
        return STREETS[self.street_index]

    @property
    def pot(self) -> int:
        return sum(seat.invested for seat in self.seats)

    def active(self) -> list[Seat]:
        return [seat for seat in self.seats if not seat.folded]

    def _commit(self, seat_index: int, amount: int) -> int:
        seat = self.seats[seat_index]
        paid = max(0, min(seat.stack, int(amount)))
        seat.stack -= paid
        seat.street_bet += paid
        seat.invested += paid
        seat.all_in = seat.stack == 0
        return paid

    def next_to_act(self) -> Optional[int]:
        self.pending = {i for i in self.pending if self.seats[i].can_act()}
        if len(self.active()) <= 1 or not self.pending:
            return None
        for offset in range(PLAYERS):
            candidate = (self.cursor + offset) % PLAYERS
            if candidate in self.pending:
                return candidate
        return None

    def legal_state(self, seat_index: int) -> dict:
        seat = self.seats[seat_index]
        if seat_index not in self.pending or not seat.can_act():
            return {"legal": [], "to_call": 0, "min_raise_to": 0, "max_raise_to": 0, "can_raise": False}
        to_call = max(0, self.current_bet - seat.street_bet)
        maximum = seat.street_bet + seat.stack
        minimum = self.current_bet + self.last_full_raise
        reopened = (
            not seat.has_acted
            or not seat.acted_on_wager
            or self.current_bet - seat.acted_facing_bet >= self.last_full_raise
        )
        can_raise = reopened and maximum >= minimum
        legal = ["check"] if to_call == 0 else ["fold", "call"]
        if can_raise:
            # The strategy API uses `raise` for both opening a street and
            # raising an existing wager. Public replay events project the
            # former as `bet`; the replay adapter maps it back to `raise`.
            legal.append("raise")
        if seat.stack > 0 and (maximum <= self.current_bet or reopened):
            legal.append("allin")
        return {
            "legal": legal,
            "to_call": to_call,
            "min_raise_to": minimum,
            "max_raise_to": maximum,
            "can_raise": can_raise,
        }

    def view(self, seat_index: int) -> dict:
        legal = self.legal_state(seat_index)
        seat = self.seats[seat_index]
        return {
            "rules": SIMULATION_VERSION,
            "street": self.street,
            "board": list(self.board),
            "button": self.button,
            "pot": self.pot,
            "level": {"sb": SB, "bb": BB, "ante": 0},
            "me": {
                "seat": seat_index, "player": seat.player, "cards": list(seat.hole),
                "stack": seat.stack, "bet": seat.street_bet, "invested": seat.invested,
                "position": POSITIONS[(seat_index - self.button) % PLAYERS],
            },
            "players": [
                {
                    "seat": item.seat, "player": item.player, "stack": item.stack,
                    "bet": item.street_bet, "invested": item.invested,
                    "state": "folded" if item.folded else ("allin" if item.all_in else "in"),
                    "position": POSITIONS[(item.seat - self.button) % PLAYERS],
                }
                for item in self.seats
            ],
            "actions": list(self.history),
            "toCall": legal["to_call"],
            "minRaiseTo": legal["min_raise_to"],
            "maxRaiseTo": legal["max_raise_to"],
            "canRaise": legal["can_raise"],
            "legal": legal["legal"],
            "startingStack": STARTING_STACK,
        }

    def act(self, seat_index: int, action_type: str, to: Optional[int] = None) -> dict:
        expected = self.next_to_act()
        if expected != seat_index:
            raise ValueError(f"行动顺序错误：应为{expected}，收到{seat_index}")
        state = self.legal_state(seat_index)
        seat = self.seats[seat_index]
        before_bet = self.current_bet
        to_call = state["to_call"]
        # The public/training streams record an `allin` request that raises
        # for less than the minimum as the applied action `raise`. Accept that
        # normalized applied form when (and only when) it targets maxRaiseTo.
        normalized_allin_raise = (
            action_type == "raise"
            and "allin" in state["legal"]
            and to is not None
            and int(to) == state["max_raise_to"]
            and state["max_raise_to"] > self.current_bet
        )
        if action_type not in state["legal"] and not normalized_allin_raise:
            raise ValueError(f"非法动作 {action_type}，合法动作：{state['legal']}")

        record = {"seat": seat_index, "player": seat.player, "street": self.street, "type": action_type}
        full_raise = False
        if action_type == "fold":
            seat.folded = True
        elif action_type == "check":
            pass
        elif action_type == "call":
            record["amount"] = self._commit(seat_index, to_call)
            record["to"] = seat.street_bet
        else:
            target = state["max_raise_to"] if action_type == "allin" else int(to or 0)
            if target > state["max_raise_to"] or target <= seat.street_bet:
                raise ValueError("下注目标超出范围")
            if target <= self.current_bet:
                if action_type != "allin":
                    raise ValueError("bet/raise 必须提高本街最高投入")
                record["amount"] = self._commit(seat_index, to_call)
                record["to"] = seat.street_bet
            else:
                if target < state["min_raise_to"] and target != state["max_raise_to"]:
                    raise ValueError("不足最小加注且不是全下")
                if not (not seat.has_acted or not seat.acted_on_wager or self.current_bet - seat.acted_facing_bet >= self.last_full_raise):
                    raise ValueError("短全下未重新开放加注")
                record["amount"] = self._commit(seat_index, target - seat.street_bet)
                record["to"] = seat.street_bet
                increase = target - before_bet
                full_raise = increase >= self.last_full_raise
                self.current_bet = target
                if full_raise:
                    self.last_full_raise = increase

        self.pending.discard(seat_index)
        seat.has_acted = True
        seat.acted_facing_bet = self.current_bet
        seat.acted_on_wager = before_bet > 0 or action_type in ("bet", "raise", "allin")
        if self.current_bet > before_bet:
            if full_raise:
                self.pending = {item.seat for item in self.seats if item.can_act() and item.seat != seat_index}
                for item in self.seats:
                    if item.seat != seat_index:
                        item.has_acted = False
                        item.acted_on_wager = False
            else:
                self.pending.update(
                    item.seat for item in self.seats
                    if item.can_act() and item.seat != seat_index and item.street_bet < self.current_bet
                )
        self.cursor = (seat_index + 1) % PLAYERS
        self.history.append(record)
        return record

    def advance_street(self, cards: list[str]) -> None:
        if self.next_to_act() is not None:
            raise ValueError("下注轮尚未结束")
        if len(self.active()) <= 1 or self.street_index >= 3:
            raise ValueError("当前牌局不能进入下一街")
        expected = 3 if self.street_index == 0 else 1
        if len(cards) != expected or any(card in self.board or card in sum(self.holes, []) for card in cards):
            raise ValueError("公共牌数量错误或重复")
        self.board.extend(cards)
        self.street_index += 1
        self.current_bet = 0
        self.last_full_raise = BB
        for seat in self.seats:
            seat.street_bet = 0
            seat.has_acted = False
            seat.acted_facing_bet = 0
            seat.acted_on_wager = False
        self.pending = {seat.seat for seat in self.seats if seat.can_act()}
        self.cursor = (self.button + 1) % PLAYERS

    def refund_uncalled(self) -> None:
        contributors = sorted((seat.invested, seat.seat) for seat in self.seats if seat.invested > 0)
        if len(contributors) < 2:
            return
        highest, seat_index = contributors[-1]
        second = contributors[-2][0]
        if highest > second:
            amount = highest - second
            seat = self.seats[seat_index]
            seat.invested -= amount
            seat.stack += amount
            self.refunds.append({"seat": seat_index, "amount": amount})

    def side_pots(self) -> list[dict]:
        levels = sorted({seat.invested for seat in self.seats if seat.invested > 0})
        previous = 0
        pots = []
        for level in levels:
            contributors = [seat for seat in self.seats if seat.invested >= level]
            amount = (level - previous) * len(contributors)
            eligible = [seat.seat for seat in contributors if not seat.folded]
            if amount and eligible:
                pots.append({"amount": amount, "eligible": eligible})
            previous = level
        return pots

    def settle(self) -> list[int]:
        if self.settled:
            raise ValueError("牌局已经结算")
        self.refund_uncalled()
        active = self.active()
        if len(active) == 1:
            active[0].stack += self.pot
        else:
            if len(self.board) != 5:
                raise ValueError("多人摊牌必须有5张公共牌")
            scores = {seat.seat: evaluate(seat.hole + self.board) for seat in active}
            # The official simulator coalesces pot layers that resolve to the
            # same winner set before dividing chips.  Dividing every layer
            # independently can manufacture offsetting odd chips when folded
            # dead money creates several layers (for example 250 + 200 + 1686
            # split by the same three winners must pay 712 each).
            awards_by_winners: dict[tuple[int, ...], int] = {}
            for side_pot in self.side_pots():
                best = max(scores[index] for index in side_pot["eligible"])
                winners = [index for index in side_pot["eligible"] if scores[index] == best]
                winners.sort(key=lambda index: (index - self.button - 1) % PLAYERS)
                key = tuple(winners)
                awards_by_winners[key] = awards_by_winners.get(key, 0) + side_pot["amount"]
            for winners, amount in awards_by_winners.items():
                share, remainder = divmod(amount, len(winners))
                for position, winner in enumerate(winners):
                    self.seats[winner].stack += share + (1 if position < remainder else 0)
        self.settled = True
        initial = self.starting_stacks or [STARTING_STACK] * PLAYERS
        net = [self.seats[i].stack - initial[i] for i in range(PLAYERS)]
        if sum(net) != 0:
            raise AssertionError(f"资金不守恒：{sum(net)}")
        return net


def participant_for_seat(seat: int, rotation: int) -> int:
    return (seat + rotation) % PLAYERS


def duplicate_schedule(buttons: list[int]) -> list[dict]:
    if len(buttons) != 40 or any(not 0 <= button < PLAYERS for button in buttons):
        raise ValueError("复式赛程需要40个合法按钮位")
    return [
        {
            "global_hand": rotation * 40 + hand + 1,
            "rotation": rotation,
            "rotation_hand": hand + 1,
            "deal_index": hand,
            "button": buttons[hand],
            "participants_by_seat": [participant_for_seat(seat, rotation) for seat in range(PLAYERS)],
            "reset_context": hand == 0,
        }
        for rotation in range(6)
        for hand in range(40)
    ]
