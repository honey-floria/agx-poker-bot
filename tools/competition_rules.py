#!/usr/bin/env python3
"""Fail closed when the audited AGX competition contract changes."""

from __future__ import annotations

import out
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "config" / "competition.out"
AUDITED_RULES_VERSION = "rsi-poker-4.1"


def load_and_check_rules() -> dict:
    rules = out.loads(MANIFEST.read_text(encoding="utf-8"))
    errors = []
    if rules.get("rulesVersion") != AUDITED_RULES_VERSION:
        errors.append(
            f"规则版本为 {rules.get('rulesVersion')!r}，已审计版本为 {AUDITED_RULES_VERSION!r}"
        )
    if rules.get("auditStatus") != "confirmed":
        errors.append("规则审计状态不是 confirmed")

    table = rules.get("table", {})
    match = rules.get("match", {})
    limits = rules.get("limits", {})
    expected = {
        "schemaVersion": (rules.get("schemaVersion"), 1),
        "table.players": (table.get("players"), 6),
        "table.game": (table.get("game"), "no-limit-holdem"),
        "table.format": (table.get("format"), "cash"),
        "table.smallBlind": (table.get("smallBlind"), 50),
        "table.bigBlind": (table.get("bigBlind"), 100),
        "table.ante": (table.get("ante"), 0),
        "table.startingStack": (table.get("startingStack"), 10_000),
        "match.hands": (match.get("hands"), 240),
        "match.rotations": (match.get("rotations"), 6),
        "match.handsPerRotation": (match.get("handsPerRotation"), 40),
        "limits.actionMs": (limits.get("actionMs"), 200),
        "limits.initializationMs": (limits.get("initializationMs"), 2_000),
        "limits.seatCpuMsPerMatch": (limits.get("seatCpuMsPerMatch"), 20_000),
        "limits.sourceBytes": (limits.get("sourceBytes"), 4_194_304),
        "limits.heapBytes": (limits.get("heapBytes"), 128 * 1024 * 1024),
        "limits.stackBytes": (limits.get("stackBytes"), 1024 * 1024),
    }
    for name, (actual, wanted) in expected.items():
        if actual != wanted:
            errors.append(f"{name}={actual!r}，应为 {wanted!r}")

    reset_hands = [1 + i * match.get("handsPerRotation", 0) for i in range(match.get("rotations", 0))]
    if match.get("resetContextBeforeHands") != reset_hands:
        errors.append("策略上下文重置手数与阶段边界不一致")
    if match.get("hands") != match.get("rotations", 0) * match.get("handsPerRotation", 0):
        errors.append("总手数不等于阶段数乘以每阶段手数")
    if table.get("resetStacksEachHand") is not True:
        errors.append("table.resetStacksEachHand 必须为 true")
    for name in ("repeatPhysicalDeals", "repeatButtonSequence", "eachParticipantVisitsAllSeats"):
        if match.get(name) is not True:
            errors.append(f"match.{name} 必须为 true")
    if match.get("crossRotationMemory") is not False:
        errors.append("match.crossRotationMemory 必须为 false")
    if rules.get("actions", {}).get("toIsStreetTotal") is not True:
        errors.append("actions.toIsStreetTotal 必须为 true")
    deployment = rules.get("deployment", {})
    if deployment.get("network") is not False or deployment.get("externalModelFiles") is not False:
        errors.append("部署必须禁用网络和外部模型文件")
    scoring = rules.get("scoring", {})
    if scoring.get("rankingMetric") != "real_chip_net_over_240_hands":
        errors.append("排名必须使用240手累计真实筹码净额")
    if scoring.get("ratingSystem") != "OpenSkill":
        errors.append("天梯系统必须为 OpenSkill")

    if errors:
        raise RuntimeError("比赛约束检查失败：\n- " + "\n- ".join(errors))
    return rules


if __name__ == "__main__":
    checked = load_and_check_rules()
    print(f"competition rules: ok ({checked['rulesVersion']})")
