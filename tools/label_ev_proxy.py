#!/usr/bin/env python3
"""Attach reproducible equity-based EV proxy labels to difficult replay states."""

from __future__ import annotations

import argparse
from collections import Counter
import json
import math
from pathlib import Path
import random
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "neural"))
sys.path.insert(0, str(ROOT / "tools"))
from data import estimate_equity  # noqa: E402
from replay_data import ACTIONS, action_bucket  # noqa: E402
from build_replay_dataset import display_path, sha256_file, write_json_atomic  # noqa: E402


STREETS = ("preflop", "flop", "turn", "river")
POSITIONS = ("BTN", "SB", "BB", "UTG", "HJ", "CO")
FRACTIONS = (0.33, 0.50, 0.75, 1.00, 1.50, 2.00)


def decision_state(row: dict) -> dict:
    history = list(row.get("history", []))
    active = [item for item in row.get("players", []) if item.get("state") in ("in", "allin")]
    opponents = max(1, len(active) - 1)
    return {
        "street": STREETS.index(row["street"]),
        "position": POSITIONS.index(row["position"]),
        "hole": list(row["hole"]),
        "board": list(row.get("board", [])),
        "pot": max(0, int(row.get("pot", 0))),
        "to_call": max(0, int(row.get("to_call", 0))),
        "stack": max(0, int(row.get("stack", 0))),
        "invested": max(0, int(row.get("invested", 0))),
        "opponents": opponents,
        "preflop_raises": sum(
            item.get("street") == "preflop" and item.get("type") in ("bet", "raise", "allin") for item in history
        ),
        "street_raises": sum(
            item.get("street") == row["street"] and item.get("type") in ("bet", "raise", "allin") for item in history
        ),
        "callers": sum(item.get("street") == row["street"] and item.get("type") == "call" for item in history),
        "can_raise": bool(
            row.get("can_raise")
            if row.get("can_raise") is not None
            else ("raise" in row.get("legal", []) or "bet" in row.get("legal", []))
        ),
    }


def _softmax_evs(evs: list[float | None], temperature: float) -> list[float]:
    legal = [value for value in evs if value is not None]
    maximum = max(legal)
    weights = [0.0 if value is None else math.exp(max(-50.0, (value - maximum) / temperature)) for value in evs]
    total = sum(weights)
    return [value / total for value in weights]


def proxy_label(row: dict, trials: int, seed: int, temperature_bb: float) -> dict:
    state = decision_state(row)
    rng = random.Random(seed)
    equity = estimate_equity(state, trials, rng)
    pot, to_call, stack = state["pot"], state["to_call"], state["stack"]
    me_bet = max(0, int(row.get("me_bet", 0)))
    minimum = max(0, int(row.get("min_raise_to", 0)))
    maximum = max(0, int(row.get("max_raise_to", me_bet + stack)))
    legal = set(row.get("legal", []))
    evs: list[float | None] = [None] * len(ACTIONS)
    if "fold" in legal:
        evs[0] = 0.0
    if "check" in legal:
        evs[1] = equity * pot
    if "call" in legal:
        evs[2] = equity * (pot + to_call) - to_call

    def aggressive_ev(target: int) -> float:
        increment = max(0, min(stack, target - me_bet))
        pressure = increment / max(1.0, pot + increment)
        per_opponent_fold = max(0.05, min(0.65, 0.12 + 0.58 * pressure - 0.05 * state["street_raises"]))
        fold_all = per_opponent_fold ** state["opponents"]
        called_pot = pot + increment + min(increment, max(to_call, pot // max(1, state["opponents"])))
        called_ev = equity * called_pot - increment
        return fold_all * pot + (1.0 - fold_all) * called_ev

    if ("raise" in legal or "bet" in legal) and state["can_raise"]:
        for offset, fraction in enumerate(FRACTIONS, start=3):
            target = math.floor(max(minimum, min(maximum, me_bet + fraction * (pot + to_call))))
            evs[offset] = aggressive_ev(target)
    if "allin" in legal:
        evs[9] = aggressive_ev(me_bet + stack)
    if not any(value is not None for value in evs):
        raise ValueError("state has no supported legal action")

    policy = _softmax_evs(evs, max(1.0, temperature_bb * 100.0))
    best = max((index for index, value in enumerate(evs) if value is not None), key=lambda index: evs[index])
    observed, _ = action_bucket(row)
    observed_ev = evs[observed]
    if observed_ev is None:
        raise ValueError(f"observed action {ACTIONS[observed]} is not legal in EV proxy")
    state_value = float(evs[best])
    standard_error = math.sqrt(max(0.0, equity * (1.0 - equity)) / trials)
    sorted_evs = sorted((value for value in evs if value is not None), reverse=True)
    margin = sorted_evs[0] - sorted_evs[1] if len(sorted_evs) > 1 else abs(sorted_evs[0])
    sampling_confidence = max(0.0, min(1.0, 1.0 - 4.0 * standard_error))
    margin_confidence = max(0.0, min(1.0, margin / max(100.0, pot)))
    confidence = 0.7 * sampling_confidence + 0.3 * margin_confidence
    ev_weight = 0.75 * confidence
    return {
        "version": "equity-ev-proxy-v1",
        "trials": trials,
        "seed": seed,
        "equity": round(equity, 8),
        "action_evs": [None if value is None else round(value, 6) for value in evs],
        "policy": [round(value, 8) for value in policy],
        "best_action_index": best,
        "best_action": ACTIONS[best],
        "state_value": round(state_value, 6),
        "observed_action_index": observed,
        "observed_regret": round(state_value - float(observed_ev), 6),
        "confidence": round(confidence, 8),
        "fusion_weights": {
            "behavior": round(1.0 - ev_weight, 8),
            "ev_proxy": round(ev_weight, 8),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="为困难翻后状态生成可复现的权益 EV 代理标签")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--trials", type=int, default=256)
    parser.add_argument("--seed", type=int, default=7607)
    parser.add_argument("--temperature-bb", type=float, default=4.0)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--include-preflop", action="store_true")
    args = parser.parse_args()
    if args.trials < 1 or args.temperature_bb <= 0 or (args.limit is not None and args.limit < 1):
        raise SystemExit("trials, temperature, and optional limit must be positive")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    counts: Counter[str] = Counter()
    regrets = confidences = 0.0
    written = skipped_preflop = 0
    with args.input.open("r", encoding="utf-8") as source, temporary.open("w", encoding="utf-8") as target:
        for line_number, line in enumerate(source, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not args.include_preflop and row.get("street") == "preflop":
                skipped_preflop += 1
                continue
            identity = f"{row.get('match_id')}:{row.get('hand')}:{row.get('player')}:{line_number}"
            local_seed = args.seed
            for character in identity:
                local_seed = ((local_seed * 16777619) ^ ord(character)) & 0xFFFFFFFF
            teacher = proxy_label(row, args.trials, local_seed, args.temperature_bb)
            enriched = dict(row)
            enriched["ev_teacher"] = teacher
            enriched["data_version"] = "public-replay-top20-ev-proxy-v1"
            target.write(json.dumps(enriched, ensure_ascii=False, separators=(",", ":")) + "\n")
            counts[teacher["best_action"]] += 1
            regrets += teacher["observed_regret"]
            confidences += teacher["confidence"]
            written += 1
            if args.limit is not None and written >= args.limit:
                break
    temporary.replace(args.output)
    report = {
        "schema": "agx.equity-ev-proxy-labels.v1",
        "teacher_version": "equity-ev-proxy-v1",
        "warning": "This is a range-constrained Monte Carlo EV proxy, not a solved equilibrium or MCCFR teacher.",
        "input": display_path(args.input),
        "input_sha256": sha256_file(args.input),
        "trials": args.trials,
        "seed": args.seed,
        "temperature_bb": args.temperature_bb,
        "include_preflop": args.include_preflop,
        "labeled": written,
        "skipped_preflop": skipped_preflop,
        "best_action_counts": dict(counts),
        "mean_observed_regret": round(regrets / max(1, written), 6),
        "mean_confidence": round(confidences / max(1, written), 8),
        "output": display_path(args.output),
        "output_sha256": sha256_file(args.output),
    }
    write_json_atomic(args.report, report)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
