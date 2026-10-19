#!/usr/bin/env python3
"""Convert authorized AGX-style hand traces into normalized decision JSONL."""

from __future__ import annotations

import argparse
import out
from pathlib import Path
import sys


DISTILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DISTILL_ROOT / "simulator"))
from engine import PokerHand, RULES_VERSION


def load_documents(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    if text.startswith("["):
        value = out.loads(text)
        return value if isinstance(value, list) else [value]
    if text.startswith("{"):
        value = out.loads(text)
        return value.get("matches", [value])
    return [out.loads(line) for line in text.splitlines() if line.strip()]


def validate_snapshot(engine: PokerHand, snapshot: dict, hand_number: int) -> None:
    expected = {
        "pot": engine.pot,
        "stacks": [seat.stack for seat in engine.seats],
        "bets": [seat.street_bet for seat in engine.seats],
        "invested": [seat.invested for seat in engine.seats],
        "states": ["folded" if seat.folded else ("allin" if seat.all_in else "in") for seat in engine.seats],
    }
    for field, actual in snapshot.items():
        if field in expected and actual != expected[field]:
            raise ValueError(f"第{hand_number}手动作前 {field} 不一致：计算{expected[field]}，回放{actual}")


def parse_match(match: dict) -> tuple[list[dict], dict]:
    if match.get("rules", RULES_VERSION) != RULES_VERSION:
        raise ValueError(f"未审计的规则版本：{match.get('rules')}")
    match_id = str(match.get("match_id", ""))
    if not match_id:
        raise ValueError("回放缺少 match_id")
    hands = match.get("hands")
    if not isinstance(hands, list):
        raise ValueError("回放缺少 hands 数组")

    identities = []
    for hand in hands:
        for player in hand.get("players", []):
            identity = str(player.get("player", ""))
            if identity and identity not in identities:
                identities.append(identity)
    anonymous = {identity: f"anon_{index + 1}" for index, identity in enumerate(identities)}
    decisions = []
    parsed_hands = 0
    match_totals = {name: 0 for name in anonymous.values()}
    for hand_data in hands:
        seats_data = sorted(hand_data.get("players", []), key=lambda item: item.get("seat", -1))
        if len(seats_data) != 6 or [item.get("seat") for item in seats_data] != list(range(6)):
            raise ValueError("每手必须包含0到5号六个座位")
        if any(not isinstance(item.get("hole"), list) or len(item["hole"]) != 2 for item in seats_data):
            raise ValueError("决策导出需要有权限的完整底牌轨迹；公开回放不足以补齐私有底牌")
        names = [anonymous[str(item["player"])] for item in seats_data]
        engine = PokerHand(
            button=int(hand_data["button"]),
            holes=[item["hole"] for item in seats_data],
            players=names,
        )
        hand_number = int(hand_data.get("hand", parsed_hands + 1))
        rotation = int(hand_data.get("rotation", (hand_number - 1) // 40))
        for event in hand_data.get("events", []):
            kind = event.get("type")
            if kind in ("flop", "turn", "river"):
                engine.advance_street(list(event.get("cards", [])))
                continue
            if kind != "action":
                raise ValueError(f"未知事件类型：{kind!r}")
            seat = int(event["seat"])
            if isinstance(event.get("state"), dict):
                validate_snapshot(engine, event["state"], hand_number)
            view = engine.view(seat)
            action_type = str(event["action"])
            actual = {"type": action_type}
            if "to" in event:
                actual["to"] = int(event["to"])
            decisions.append(
                {
                    "match_id": match_id,
                    "hand": hand_number,
                    "rotation": rotation,
                    "player": names[seat],
                    "position": view["me"]["position"],
                    "hole": view["me"]["cards"],
                    "board": view["board"],
                    "street": view["street"],
                    "pot": view["pot"],
                    "stack": view["me"]["stack"],
                    "to_call": view["toCall"],
                    "legal": view["legal"],
                    "min_raise_to": view["minRaiseTo"],
                    "max_raise_to": view["maxRaiseTo"],
                    "history": view["actions"],
                    "action": actual,
                    "final_net": None,
                }
            )
            engine.act(seat, action_type, event.get("to"))
        net = engine.settle()
        expected_net = hand_data.get("final_net")
        if expected_net is not None and [int(value) for value in expected_net] != net:
            raise ValueError(f"第{hand_number}手净额不一致：计算{net}，回放{expected_net}")
        for index, value in enumerate(net):
            match_totals[names[index]] += value
        for decision in decisions:
            if decision["match_id"] == match_id and decision["hand"] == hand_number:
                decision["final_net"] = net[names.index(decision["player"])]
        parsed_hands += 1
    for decision in decisions:
        decision["match_net"] = match_totals[decision["player"]]
        decision["final_rank"] = 1 + sum(value > decision["match_net"] for value in match_totals.values())
    ranking = sorted(match_totals.items(), key=lambda item: (-item[1], item[0]))
    return decisions, {"match_id": match_id, "hands": parsed_hands, "decisions": len(decisions), "ranking": ranking}


def main() -> None:
    parser = argparse.ArgumentParser(description="解析有权限的 AGX 扑克完整轨迹")
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    all_decisions = []
    reports = []
    for document in load_documents(args.input):
        decisions, report = parse_match(document)
        all_decisions.extend(decisions)
        reports.append(report)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "".join(out.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in all_decisions),
        encoding="utf-8",
    )
    summary = {"rules": RULES_VERSION, "matches": len(reports), "hands": sum(r["hands"] for r in reports), "decisions": len(all_decisions), "details": reports}
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(out.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(out.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
