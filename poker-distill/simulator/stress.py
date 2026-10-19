#!/usr/bin/env python3
"""Random legal-action stress test for the exact poker engine."""

import argparse
import json
from pathlib import Path
import random
import time

from engine import PLAYERS, RANKS, RULES_VERSION, SIMULATION_VERSION, STARTING_STACK, SUITS, PokerHand


def play_random_hand(rng: random.Random, hand_number: int) -> None:
    deck = [rank + suit for rank in RANKS for suit in SUITS]
    rng.shuffle(deck)
    hand = PokerHand(hand_number % PLAYERS, [deck[i * 2:i * 2 + 2] for i in range(PLAYERS)])
    board_cursor = 12
    actions = 0
    while len(hand.active()) > 1:
        while hand.next_to_act() is not None:
            actions += 1
            if actions > 200:
                raise AssertionError("单手动作超过200")
            seat = hand.next_to_act()
            state = hand.legal_state(seat)
            legal = state["legal"]
            weights = {"fold": 24, "check": 55, "call": 52, "bet": 12, "raise": 10, "allin": 2}
            action = rng.choices(legal, weights=[weights[item] for item in legal])[0]
            target = None
            if action in ("bet", "raise"):
                target = rng.randint(state["min_raise_to"], state["max_raise_to"])
            hand.act(seat, action, target)
            if sum(item.stack for item in hand.seats) + hand.pot != PLAYERS * STARTING_STACK:
                raise AssertionError("行动后桌面筹码不守恒")
        if len(hand.active()) <= 1 or hand.street_index == 3:
            break
        count = 3 if hand.street_index == 0 else 1
        hand.advance_street(deck[board_cursor:board_cursor + count])
        board_cursor += count
    net = hand.settle()
    if sum(net) != 0:
        raise AssertionError("结算净额不为零")


def main() -> None:
    parser = argparse.ArgumentParser(description="随机生成合法牌局并验证状态机")
    parser.add_argument("--hands", type=int, default=100_000)
    parser.add_argument("--seed", type=int, default=7607)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if args.hands < 1:
        raise SystemExit("hands 必须大于0")
    rng = random.Random(args.seed)
    started = time.perf_counter()
    for hand_number in range(args.hands):
        play_random_hand(rng, hand_number)
    report = {
        "rules": RULES_VERSION,
        "simulation": SIMULATION_VERSION,
        "hands": args.hands,
        "seed": args.seed,
        "illegal_states": 0,
        "deadlocks": 0,
        "zero_sum_failures": 0,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
