#!/usr/bin/env python3

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "noregrets"))
from state_mapping import PublicState, canonicalize_cards, map_decision, restore_cards, roundtrip_public


def initial_decision() -> dict:
    return {
        "match_id": "fixture",
        "hand": 1,
        "seat": 3,
        "button": 0,
        "position": "UTG",
        "hole": ["As", "Kd"],
        "board": [],
        "street": "preflop",
        "pot": 150,
        "stack": 10000,
        "me_bet": 0,
        "invested": 0,
        "to_call": 100,
        "legal": ["fold", "call", "raise", "allin"],
        "min_raise_to": 200,
        "max_raise_to": 10000,
        "can_raise": True,
        "history": [],
        "players": [
            {"seat": 0, "stack": 10000, "bet": 0, "invested": 0, "state": "in"},
            {"seat": 1, "stack": 9950, "bet": 50, "invested": 50, "state": "in"},
            {"seat": 2, "stack": 9900, "bet": 100, "invested": 100, "state": "in"},
            {"seat": 3, "stack": 10000, "bet": 0, "invested": 0, "state": "in"},
            {"seat": 4, "stack": 10000, "bet": 0, "invested": 0, "state": "in"},
            {"seat": 5, "stack": 10000, "bet": 0, "invested": 0, "state": "in"},
        ],
    }


base = initial_decision()
mapped = map_decision(base)
assert mapped["mapping_quality"] == "exact"
assert [item["to"] for item in mapped["action_menu"]] == [200, 225, 287, 350, 10000]
assert mapped["legal_families_match"] is True
roundtrip = roundtrip_public(mapped)
assert roundtrip["seat"] == base["seat"]
assert roundtrip["button"] == base["button"]
assert roundtrip["hole"] == base["hole"]

cards_a = canonicalize_cards(["Ah", "Kh"], ["Qs", "7d", "2c"])
cards_b = canonicalize_cards(["As", "Ks"], ["Qh", "7c", "2d"])
assert cards_a["key"] == cards_b["key"]
assert restore_cards(cards_a["hole"], cards_a["inverse_suit_permutation"]) == ["Ah", "Kh"]

off_tree = initial_decision()
off_tree.update({
    "seat": 4,
    "position": "HJ",
    "pot": 400,
    "stack": 10000,
    "to_call": 250,
    "min_raise_to": 400,
    "history": [{"seat": 3, "street": "preflop", "type": "raise", "amount": 250, "to": 250}],
})
off_tree["players"][3].update({"stack": 9750, "bet": 250, "invested": 250})
projected = map_decision(off_tree)
assert projected["mapping_quality"] == "projected"
assert projected["projection"]["events"][0]["actual_to"] == 250
assert projected["projection"]["events"][0]["projected_to"] == 225

no_reopen = initial_decision()
no_reopen["can_raise"] = False
no_reopen["legal"] = ["fold", "call"]
unsupported = map_decision(no_reopen)
assert unsupported["mapping_quality"] == "unsupported"
assert "real_shadow_raise_legality_divergence" in unsupported["unsupported_reasons"]

short = PublicState.initial(0)
short.stacks[5] = 250
short.apply(3, "raise", 200)
short.apply(4, "fold")
short.apply(5, "allin", 250)
assert short.bounds(3) is None

print("noregrets mapping tests: ok")
