"""Bounded deterministic development summaries; never raw market rows or ledgers."""

from __future__ import annotations

import math
from itertools import pairwise
from typing import Any

from finagent.agents.r4_contracts import AUTHORITY


def portfolio_feedback(report: dict[str, Any]) -> dict[str, Any]:
    arms = {}
    for name, costs in report["overall"].items():
        rows = [f["arms"][name]["cost_scenarios"]["5.0"] for f in report["folds"]]
        decisions = sum(r["decision_count"] for r in rows)
        arms[name] = {
            "mean_fold_return_5bp": costs["5.0"]["mean_fold_compounded_return"],
            "worst_fold_return_5bp": costs["5.0"]["worst_fold_compounded_return"],
            "drawdown_5bp": max(
                (
                    r["daily_close_max_drawdown"]
                    for r in rows
                    if r["daily_close_max_drawdown"] is not None
                ),
                default=None,
            ),
            "turnover_5bp": math.fsum(r["turnover"] for r in rows),
            "fallback_rate": sum(r["fallback_count"] for r in rows) / decisions
            if decisions
            else None,
            "factor_concentration": math.fsum(
                r["mean_factor_weight_concentration"] * r["decision_count"]
                for r in rows
                if r["mean_factor_weight_concentration"] is not None
            )
            / decisions
            if decisions
            else None,
            "evaluable_folds": costs["5.0"]["evaluable_fold_count"],
            "unavailable_sessions": sum(r["unresolved_sessions"] for r in rows),
            "unavailable_signal_frames": sum(r["unavailable_signal_frames"] for r in rows),
            "cost_sensitivity": {
                c: {
                    "mean_fold_return": v["mean_fold_compounded_return"],
                    "worst_fold_return": v["worst_fold_compounded_return"],
                }
                for c, v in costs.items()
            },
        }
    reference = arms["equal_weight"]["mean_fold_return_5bp"]
    for values in arms.values():
        mean = values["mean_fold_return_5bp"]
        values["difference_to_equal_weight_5bp"] = (
            mean - reference if mean is not None and reference is not None else None
        )
    changes = []
    for fold in report["folds"]:
        for session in fold["market_states"]:
            for before, after in pairwise(session):
                if before["probabilities"] is not None and after["probabilities"] is not None:
                    changes.append(
                        math.fsum(
                            abs(a - b)
                            for a, b in zip(before["probabilities"], after["probabilities"])
                        )
                        / 2
                    )
    return {
        "arms": arms,
        "state_probability_mean_change": math.fsum(changes) / len(changes) if changes else None,
        "comparison_scope": "same_pool_all_five_arms; independent_fold_NAV; development_descriptive",
        **AUTHORITY,
    }


def compare_feedback(experiments: list[dict[str, Any]]) -> dict[str, Any]:
    compatible = len({r["compatibility_id"] for r in experiments}) == 1
    pairs = [
        {
            "left": a["experiment_id"],
            "right": b["experiment_id"],
            "factor_overlap": len(set(a["factor_ids"]) & set(b["factor_ids"]))
            / len(set(a["factor_ids"]) | set(b["factor_ids"])),
        }
        for i, a in enumerate(experiments)
        for b in experiments[i + 1 :]
    ]
    return {
        "outcome": "EXPERIMENTS_COMPARED" if compatible else "NOT_COMPARABLE",
        "compatible_source_folds_cost_execution": compatible,
        "experiments": [
            {
                "experiment_id": r["experiment_id"],
                "allocator": r["preferred_allocator"],
                "metrics_5bp": {
                    k: v
                    for k, v in r["summary"]["arms"][r["preferred_allocator"]].items()
                    if k != "cost_sensitivity"
                }
                if compatible
                else None,
                "resource_cost": r["resource_cost"],
            }
            for r in experiments
        ],
        "factor_set_overlap": pairs,
        **AUTHORITY,
    }
