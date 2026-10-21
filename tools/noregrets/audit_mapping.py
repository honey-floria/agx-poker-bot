#!/usr/bin/env python3
"""Deterministically audit a stratified sample of AGX decisions."""

from __future__ import annotations

import argparse
import hashlib
import heapq
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

from state_mapping import map_decision


def identity(row: dict) -> str:
    return f"{row.get('match_id')}:{row.get('hand')}:{row.get('seat')}:{len(row.get('history', []))}"


def stratum(row: dict) -> str:
    active = sum(item.get("state") in ("in", "allin") for item in row.get("players", []))
    return f"{row.get('street')}:{'hu' if active == 2 else 'multi'}"


def select(path: Path, sample_size: int, per_stratum: int, seed: int) -> tuple[list[dict], str, int]:
    counts = Counter()
    digest = hashlib.sha256()
    rows = 0
    with path.open("rb") as raw:
        for line in raw:
            digest.update(line)
            if not line.strip():
                continue
            row = json.loads(line)
            rows += 1
            counts[stratum(row)] += 1
    quotas = {key: min(per_stratum, count) for key, count in counts.items()}
    remaining = sample_size - sum(quotas.values())
    while remaining > 0:
        progressed = False
        for key in sorted(quotas):
            if quotas[key] < counts[key]:
                quotas[key] += 1
                remaining -= 1
                progressed = True
                if remaining == 0:
                    break
        if not progressed:
            break

    heaps: dict[str, list[tuple[int, int, dict]]] = defaultdict(list)
    with path.open("r", encoding="utf-8") as handle:
        for row_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            key = stratum(row)
            score = int.from_bytes(hashlib.sha256(f"{seed}:{identity(row)}".encode()).digest()[:8], "big")
            entry = (-score, row_number, row)
            heap = heaps[key]
            if len(heap) < quotas[key]:
                heapq.heappush(heap, entry)
            elif entry > heap[0]:
                heapq.heapreplace(heap, entry)
    sample = [entry[2] for key in sorted(heaps) for entry in sorted(heaps[key], reverse=True)]
    return sample, digest.hexdigest(), rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit AGX -> NoRegrets state mapping")
    parser.add_argument("input", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--sample-size", type=int, default=10_000)
    parser.add_argument("--per-stratum", type=int, default=1250)
    parser.add_argument("--seed", type=int, default=7607)
    args = parser.parse_args()
    sample, source_hash, source_rows = select(args.input, args.sample_size, args.per_stratum, args.seed)
    quality = Counter()
    by_stratum: dict[str, Counter] = defaultdict(Counter)
    reasons = Counter()
    coverage = Counter()
    failures = []
    max_chips = 0
    max_log = 0.0
    exact_legal_mismatches = 0
    nan_count = 0
    for row in sample:
        key = stratum(row)
        legal = set(row.get("legal", []))
        coverage["check"] += "check" in legal
        coverage["call"] += "call" in legal
        coverage["normal_raise"] += "raise" in legal or "bet" in legal
        agx_can_raise = bool(row["can_raise"]) if "can_raise" in row else bool({"raise", "bet"} & legal)
        coverage["cannot_raise"] += not agx_can_raise
        action = row.get("action", {})
        action_to = action.get("to")
        allin_action = action.get("type") == "allin" or (
            action.get("type") in ("raise", "bet")
            and action_to is not None
            and int(action_to) == int(row.get("max_raise_to", -1))
        )
        coverage["allin"] += allin_action
        coverage["short_allin"] += allin_action and int(row.get("max_raise_to", 0)) < int(row.get("min_raise_to", 0))
        coverage["multiway"] += key.endswith(":multi")
        try:
            mapped = map_decision(row)
        except Exception as exc:  # report every bad production row; do not hide it
            failures.append({"state": identity(row), "error": str(exc)})
            continue
        q = mapped["mapping_quality"]
        quality[q] += 1
        by_stratum[key][q] += 1
        reasons.update(mapped["unsupported_reasons"])
        max_chips = max(max_chips, mapped["projection"]["max_error_chips"])
        max_log = max(max_log, mapped["projection"]["max_error_log"])
        exact_legal_mismatches += q == "exact" and not mapped["legal_families_match"]
        values = [mapped["projection"]["max_error_log"]]
        nan_count += any(not math.isfinite(float(value)) for value in values)

    expected_strata = {f"{street}:{kind}" for street in ("preflop", "flop", "turn", "river") for kind in ("hu", "multi")}
    gate_passed = (
        len(sample) >= 10_000
        and not failures
        and nan_count == 0
        and exact_legal_mismatches == 0
        and expected_strata.issubset(by_stratum)
    )
    report = {
        "schema": "agx.noregrets-mapping-audit.v1",
        "upstream_commit": "757f7692738069522195d2b486eec60a8b010c0c",
        "source": str(args.input),
        "source_sha256": source_hash,
        "source_rows": source_rows,
        "sample_seed": args.seed,
        "sample_rows": len(sample),
        "stratification": "street x heads-up/multiway",
        "mapping_quality": dict(sorted(quality.items())),
        "by_stratum": {key: dict(sorted(value.items())) for key, value in sorted(by_stratum.items())},
        "unsupported_reasons": dict(sorted(reasons.items())),
        "coverage": dict(sorted(coverage.items())),
        "max_projection_error_chips": max_chips,
        "max_projection_error_log": max_log,
        "crashes": len(failures),
        "failure_examples": failures[:50],
        "nan_count": nan_count,
        "exact_legal_mismatches": exact_legal_mismatches,
        "gate_ng2_mapping_integrity": "passed" if gate_passed else "failed",
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    if not gate_passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
