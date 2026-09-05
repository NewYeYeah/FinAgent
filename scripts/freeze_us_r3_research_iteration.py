from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from finagent.research.us_r3_agent_boundary import (
    build_us_r3_research_iteration_plan,
    canonical_us_r3_agent_boundary_policy,
)
from finagent.research.us_r3_alpha_catalog import (
    build_us_r3_executable_frontier_candidates,
    build_us_r3_frontier_alpha_catalog,
)


def _canonical_hash(payload: object, *, prefix: str) -> str:
    rendered = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(rendered).hexdigest()[:24]}"


def build_bundle() -> dict[str, object]:
    policy = canonical_us_r3_agent_boundary_policy()
    catalog = build_us_r3_frontier_alpha_catalog()
    candidates = build_us_r3_executable_frontier_candidates()
    plan = build_us_r3_research_iteration_plan(candidates)
    payload: dict[str, object] = {
        "schema_version": "finagent.us-r3-research-iteration-bundle.v1",
        "agent_boundary_policy": policy.to_dict(),
        "frontier_alpha_catalog": [item.to_dict() for item in catalog],
        "preregistered_executable_candidates": [item.to_dict() for item in candidates],
        "research_iteration_plan": plan.to_dict(),
        "financial_data_read": False,
        "external_model_called": False,
        "mt5_accessed": False,
        "financial_performance_evaluated": False,
        "alpha_gate_evaluated": False,
        "execution_authority": False,
    }
    payload["bundle_id"] = _canonical_hash(payload, prefix="us-r3-research-bundle")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Freeze the data-blind, MT5-free US-R3 Agent/Alpha research iteration."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/us_r3/us_r3_research_iteration_bundle.json"),
    )
    args = parser.parse_args()
    bundle = build_bundle()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(bundle, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"bundle_id": bundle["bundle_id"], "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
