#!/usr/bin/env python3

import out
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "poker-distill" / "simulator"))
from engine import PokerHand, duplicate_schedule, evaluate
sys.path.insert(0, str(ROOT / "tools"))
from environment_gate import require_training_allowed


HOLES = [["As", "Ah"], ["Ks", "Kh"], ["Qs", "Qh"], ["Js", "Jh"], ["Ts", "Th"], ["9s", "9h"]]

assert evaluate(["As", "Ah", "Ad", "Ks", "Kh", "Kd", "2c"])[:3] == (6, 14, 13)
require_training_allowed(10_000, pipeline_smoke=True)
try:
    require_training_allowed(10_001, pipeline_smoke=True)
    raise AssertionError("large-scale environment gate did not block training")
except RuntimeError:
    pass


def fold_to_winner(hand: PokerHand) -> None:
    while hand.next_to_act() is not None and len(hand.active()) > 1:
        hand.act(hand.next_to_act(), "fold")


# Blinds, reset stack and `to` as a street-total target.
hand = PokerHand(5, HOLES)
assert hand.pot == 150
assert [seat.stack for seat in hand.seats[:2]] == [9950, 9900]
hand.act(2, "raise", 300)
assert hand.seats[2].street_bet == 300 and hand.seats[2].stack == 9700

# A single short all-in does not reopen raising for players who already acted.
hand = PokerHand(5, HOLES, starting_stacks=[10000, 10000, 10000, 10000, 350, 10000])
hand.act(2, "raise", 300)
hand.act(3, "call")
hand.act(4, "allin")
hand.act(5, "fold")
hand.act(0, "fold")
hand.act(1, "fold")
assert hand.next_to_act() == 2
assert hand.legal_state(2)["can_raise"] is False
hand.act(2, "call")
assert hand.legal_state(3)["can_raise"] is False
hand.act(3, "call")
assert hand.next_to_act() is None

# Multiple short all-ins whose cumulative increase reaches a full raise reopen action.
hand = PokerHand(5, HOLES, starting_stacks=[10000, 10000, 10000, 10000, 350, 500])
hand.act(2, "raise", 300)
hand.act(3, "call")
hand.act(4, "allin")
hand.act(5, "allin")
hand.act(0, "fold")
hand.act(1, "fold")
assert hand.next_to_act() == 2
assert hand.legal_state(2)["can_raise"] is True

# Uncalled all-in excess is returned before showdown.
hand = PokerHand(5, HOLES, starting_stacks=[1000, 600, 10000, 10000, 10000, 10000])
for seat in (2, 3, 4, 5):
    hand.act(seat, "fold")
hand.act(0, "allin")
hand.act(1, "allin")
hand.advance_street(["2c", "3d", "4c"])
hand.advance_street(["5d"])
hand.advance_street(["7c"])
net = hand.settle()
assert hand.refunds == [{"seat": 0, "amount": 400}]
assert sum(net) == 0

# Main pot, two side pots and folded dead money.
hand = PokerHand(5, HOLES, starting_stacks=[100, 200, 300, 300, 10000, 10000])
contributions = [100, 200, 300, 300, 0, 0]
for index, contribution in enumerate(contributions):
    seat = hand.seats[index]
    seat.invested = contribution
    seat.street_bet = contribution
    seat.stack = (hand.starting_stacks[index] - contribution)
    seat.folded = index >= 3
    seat.all_in = seat.stack == 0
hand.board = ["2c", "3d", "4c", "7d", "8c"]
hand.pending.clear()
net = hand.settle()
assert net == [300, 100, -100, -300, 0, 0]

# Odd chip goes clockwise to the first winner left of the button.
tie_holes = [["As", "Kd"], ["Ah", "Kc"], ["9s", "9h"], ["8s", "8h"], ["7s", "7h"], ["6s", "6h"]]
hand = PokerHand(5, tie_holes, starting_stacks=[101, 101, 101, 10000, 10000, 10000])
for index, seat in enumerate(hand.seats):
    seat.invested = 101 if index < 3 else 0
    seat.street_bet = seat.invested
    seat.stack = (hand.starting_stacks[index] - seat.invested)
    seat.folded = index >= 3
hand.board = ["Qs", "Js", "Ts", "2c", "3d"]
hand.pending.clear()
net = hand.settle()
assert net[0] == 51 and net[1] == 50

# Six rotations reuse 40 physical deals/buttons and visit all seats.
schedule = duplicate_schedule([index % 6 for index in range(40)])
assert len(schedule) == 240
assert [row["global_hand"] for row in schedule if row["reset_context"]] == [1, 41, 81, 121, 161, 201]
for participant in range(6):
    seats = {
        seat
        for row in schedule
        for seat, value in enumerate(row["participants_by_seat"])
        if value == participant
    }
    assert seats == set(range(6))
for deal_index in range(40):
    rows = [row for row in schedule if row["deal_index"] == deal_index]
    assert len(rows) == 6 and len({row["button"] for row in rows}) == 1

# Replay parsing restores pre-action states, anonymizes players and checks net.
replay = {
    "rules": "rsi-poker-4.1",
    "match_id": "fixture-match",
    "hands": [{
        "hand": 1,
        "rotation": 0,
        "button": 5,
        "players": [{"seat": i, "player": f"account-{i}", "hole": cards} for i, cards in enumerate(HOLES)],
        "events": [
            {"type": "action", "seat": 2, "action": "raise", "to": 300, "state": {
                "pot": 150,
                "stacks": [9950, 9900, 10000, 10000, 10000, 10000],
                "bets": [50, 100, 0, 0, 0, 0],
                "invested": [50, 100, 0, 0, 0, 0],
                "states": ["in", "in", "in", "in", "in", "in"],
            }},
            *({"type": "action", "seat": seat, "action": "fold"} for seat in (3, 4, 5, 0, 1)),
        ],
        "final_net": [-50, -100, 150, 0, 0, 0],
    }],
}
with tempfile.TemporaryDirectory(prefix="agx-replay-") as temporary:
    folder = Path(temporary)
    source, output, report = folder / "replay.out", folder / "decisions.jsonl", folder / "report.out"
    source.write_text(out.dumps(replay), encoding="utf-8")
    result = subprocess.run(
        ["python3", str(ROOT / "poker-distill" / "replay-parser" / "parse_replay.py"), str(source), str(output), "--report", str(report)],
        cwd=ROOT, text=True, capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    decisions = [out.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert len(decisions) == 6
    assert decisions[0]["player"] == "anon_3"
    assert decisions[0]["pot"] == 150 and decisions[0]["action"] == {"type": "raise", "to": 300}
    assert decisions[-1]["final_net"] == -100
    assert decisions[0]["match_net"] == 150 and decisions[0]["final_rank"] == 1
    assert out.loads(report.read_text(encoding="utf-8"))["hands"] == 1

print("exact engine and replay parser tests: ok")
