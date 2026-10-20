#!/usr/bin/env python3
"""Combine the audited heuristic with a confidence-gated behavior clone."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from competition_rules import load_and_check_rules  # noqa: E402


def wrapped(name: str, source: str, exports: str) -> str:
    return f"var {name}=(function(){{\n{source}\nreturn {{{exports}}};\n}})();\n"


def main() -> None:
    rules = load_and_check_rules()
    parser = argparse.ArgumentParser(description="导出启发式安全回退 + 高置信度行为克隆混合策略")
    parser.add_argument("--heuristic", type=Path, default=ROOT / "submission.js")
    parser.add_argument("--neural", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--min-confidence", type=float, default=0.95)
    parser.add_argument("--allow-preflop", action="store_true")
    parser.add_argument("--require-family-agreement", action="store_true")
    args = parser.parse_args()
    if not 0.0 <= args.min_confidence <= 1.0:
        raise SystemExit("min-confidence must be within [0, 1]")

    heuristic = args.heuristic.read_text(encoding="utf-8")
    neural = args.neural.read_text(encoding="utf-8")
    source = "/* Generated confidence-gated hybrid. */\n"
    source += wrapped("HEURISTIC", heuristic, "act:act")
    source += wrapped(
        "NEURAL", neural,
        "act:act,decide:decide,features:features,predict:predict,legalMask:legalMask",
    )
    source += f"""
var HYBRID_MIN_CONFIDENCE={args.min_confidence!r};
var HYBRID_ALLOW_PREFLOP={'true' if args.allow_preflop else 'false'};
var HYBRID_REQUIRE_AGREEMENT={'true' if args.require_family_agreement else 'false'};
function hybridFamily(action){{
  if(!action)return "";
  return action.type==="bet"||action.type==="raise"?"raise":action.type;
}}
function hybridConfidence(prediction,legal){{
  var logits=prediction.familyLogits,max=-Infinity,sum=0,i;
  for(i=0;i<logits.length;i++)if(legal[i]&&logits[i]>max)max=logits[i];
  for(i=0;i<logits.length;i++)if(legal[i])sum+=Math.exp(logits[i]-max);
  return 1/Math.max(1,sum);
}}
function act(view){{
  var fallback=HEURISTIC.act(view);
  try{{
    if(!HYBRID_ALLOW_PREFLOP&&view.street==="preflop")return fallback;
    var legal=NEURAL.legalMask(view),prediction=NEURAL.predict(NEURAL.features(view),legal);
    if(hybridConfidence(prediction,legal)<HYBRID_MIN_CONFIDENCE)return fallback;
    var candidate=NEURAL.decide(view);
    if(HYBRID_REQUIRE_AGREEMENT&&hybridFamily(candidate)!==hybridFamily(fallback))return fallback;
    return candidate;
  }}catch(error){{return fallback;}}
}}
"""
    encoded = source.encode("utf-8")
    if len(encoded) > rules["limits"]["sourceBytes"]:
        raise SystemExit(f"hybrid exceeds {rules['limits']['sourceBytes']} bytes")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(encoded)
    print(f"exported: {args.output}")
    print(f"bytes: {len(encoded)}")


if __name__ == "__main__":
    main()
