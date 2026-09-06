"""Independent arithmetic implementation for R3 evidence, not reviewer attestation."""

from __future__ import annotations

import json
import math
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

from finagent.research.us_r3_completion import METHODS, RUNS, seal
from finagent.research.us_r3_economic_campaign import _sealed, file_digest
from finagent.research.us_r3_inference import EvidenceDesign


def require(condition: bool, code: str) -> None:
    if not condition:
        raise ValueError(code)


def audit_daily(evaluation: dict[str, Any], days: list[str]) -> None:
    """Recompute ledger arithmetic without the production accounting summarizer."""
    daily, summary = evaluation["daily"], evaluation["summary"]
    require([d["session_date"] for d in daily] == days, "daily calendar mismatch")
    complete = all(d["resolved"] is True and d["net_return"] is not None for d in daily)
    require(summary["full_period_evaluable"] == complete, "missing return silently dropped")
    require(summary["scheduled_sessions"] == len(days), "summary denominator mismatch")
    values = [d for d in daily if d["resolved"]]
    for d in values:
        require(math.isfinite(d["net_return"]) and d["net_return"] > -1, "insolvent return")
        require(
            math.isclose(
                d["cost"],
                d["gross_traded_notional"] * evaluation["cost_bps"] / 10000,
                abs_tol=1e-10,
            ),
            "cost/notional mismatch",
        )
        require(
            math.isclose(d["net_return"] + d["cost"], d["trading_pnl_before_cost"], abs_tol=1e-10),
            "daily pnl conservation mismatch",
        )
    require(summary["resolved_sessions"] == len(values), "resolved denominator mismatch")
    for key, field in (
        ("resolved_session_cost_sum", "cost"),
        ("resolved_session_gross_traded_sum", "gross_traded_notional"),
    ):
        require(
            math.isclose(summary[key], sum(d[field] for d in values), abs_tol=1e-9),
            "aggregate accounting mismatch",
        )
    if complete:
        navs = [math.prod(1 + d["net_return"] for d in daily[:i]) for i in range(len(days) + 1)]
        dd = max(1 - nav / max(navs[: i + 1]) for i, nav in enumerate(navs))
        require(
            math.isclose(summary["compounded_return"], navs[-1] - 1, abs_tol=1e-10),
            "compounding mismatch",
        )
        require(
            math.isclose(summary["daily_close_max_drawdown"], dd, abs_tol=1e-10),
            "drawdown mismatch",
        )
    else:
        require(summary["compounded_return"] is None, "incomplete return promoted")


def review_completion(root: Path, output: Path) -> dict[str, Any]:
    protocol = _sealed(root / "protocol.json", "evidence_id", "us-r3-completion-protocol-")
    summary = _sealed(root / "summary.json", "evidence_id", "us-r3-completion-")
    model = _sealed(root / "frozen_model.json", "evidence_id", "r3-frozen-model-")
    require(
        summary["protocol_id"] == model["protocol_id"] == protocol["evidence_id"], "protocol chain"
    )
    require(summary["frozen_model_id"] == model["evidence_id"], "model chain")
    economic = _sealed(
        Path(protocol["economic_protocol"]["path"]), "protocol_id", "us-r3-economic-protocol-"
    )
    for binding in [
        protocol["economic_protocol"],
        protocol["config"],
        *economic["inputs"].values(),
    ]:
        require(file_digest(Path(binding["path"])) == binding["sha256"], "source binding changed")
    splits = protocol["splits"]
    split_days = [day for days in splits.values() for day in days]
    require(sorted(split_days) == economic["sessions"], "split coverage mismatch")
    require(len(set(split_days)) == len(economic["sessions"]), "split overlap")
    require(
        max(splits["development"]) < splits["purge"][0] < min(splits["validation"])
        and max(splits["validation"]) < splits["purge"][1] < min(splits["outer_exploratory"]),
        "split chronology mismatch",
    )
    runs = []
    states: Counter[str] = Counter()
    evaluated = 0
    for method in METHODS:
        for index in range(RUNS):
            name = f"{method}-{index}"
            run = _sealed(root / "runs" / (name + ".json"), "evidence_id", "r3-pilot-run-")
            require(run["protocol_id"] == protocol["evidence_id"], "run chain mismatch")
            require(run["method"] == method and run["run"] == index, "run membership mismatch")
            require(
                [s["slot"] for s in run["slots"]] == list(range(protocol["slots_per_run"])),
                "slot denominator mismatch",
            )
            for slot in run["slots"]:
                if slot["valid"]:
                    audit_daily(slot["evaluation"], splits["development"])
                    evaluated += 1
            ledger = run["ledger"]
            if ledger:
                # URI read-only mode; auditing must not create or mutate an absent ledger.
                uri = (root / "ledgers" / (name + ".sqlite")).resolve().as_uri() + "?mode=ro"
                with sqlite3.connect(uri, uri=True) as connection:
                    connection.row_factory = sqlite3.Row
                    actual = [
                        dict(r)
                        for r in connection.execute(
                            "SELECT request_id,slot,ordinal,state,charged_tokens,charged_cost,evaluation_reserved,wire_digest,candidate_id FROM attempts ORDER BY rowid"
                        )
                    ]
                require(actual == ledger["attempts"], "SQLite/report attempts mismatch")
                require(ledger["attempt_count"] == len(actual), "attempt count mismatch")
                require(
                    sum(a["charged_cost"] for a in actual) == ledger["charged_cost_microusd"],
                    "charge mismatch",
                )
                require(
                    sum(a["evaluation_reserved"] for a in actual) == ledger["evaluation_calls"],
                    "evaluation count mismatch",
                )
                require(
                    ledger["charged_cost_microusd"]
                    <= protocol["runtime_policy"]["maximum_cost_microusd"],
                    "run cost breach",
                )
                states.update(a["state"] for a in actual)
            runs.append(run)
    ids = [r["evidence_id"] for r in runs]
    require(ids == model["run_evidence_ids"] == summary["run_evidence_ids"], "run identity chain")
    members = []
    for run in runs:
        eligible = [
            s
            for s in run["slots"]
            if s["valid"]
            and s["evaluation"]["summary"]["full_period_evaluable"]
            and s["evaluation"]["summary"]["compounded_return"] > 0
        ]
        eligible.sort(
            key=lambda s: (-s["evaluation"]["summary"]["compounded_return"], s["candidate_id"])
        )
        members.append(
            {
                "method": run["method"],
                "run": run["run"],
                "candidate_id": eligible[0]["candidate_id"] if eligible else "cash",
                "action": eligible[0]["action"] if eligible else None,
            }
        )
    require(members == model["members"], "post-development selection mismatch")
    require(summary["valid_slots"] == evaluated, "valid denominator mismatch")
    require(
        summary["slot_denominator"] == len(runs) * protocol["slots_per_run"],
        "full denominator mismatch",
    )
    require(
        summary["charged_cost_upper_microusd"]
        == sum(r["ledger"].get("charged_cost_microusd", 0) for r in runs),
        "total cost mismatch",
    )
    caches = {}
    for partition in ("validation", "outer_exploratory"):
        for path in (root / partition).glob("*.json"):
            evaluation = _sealed(path, "evidence_id", "r3-evaluation-")
            audit_daily(evaluation, splits[partition])
            key = (
                partition,
                evaluation["candidate_id"],
                float(evaluation["cost_bps"]),
                evaluation["delay_bars"],
            )
            require(key not in caches, "duplicate economic cache")
            caches[key] = evaluation
    require(len(summary["assessments"]) == 2 * len(members), "assessment denominator mismatch")
    expected = {
        (p, m["method"], m["run"]): m["candidate_id"]
        for p in ("validation", "outer_exploratory")
        for m in members
    }
    for a in summary["assessments"]:
        require(
            expected.pop((a["partition"], a["method"], a["run"])) == a["candidate_id"],
            "assessment selection mismatch",
        )
        for cost in (0.0, 1.0, 5.0, 10.0):
            require(
                a["cost_summaries"][str(cost)]
                == caches[(a["partition"], a["candidate_id"], cost, 1)]["summary"],
                "assessment cost mismatch",
            )
        require(
            a["two_bar_delay"] == caches[(a["partition"], a["candidate_id"], 5.0, 2)]["summary"],
            "stress mismatch",
        )
    require(not expected, "missing assessments")
    manifest_path = root / "implementation-manifest.json"
    snapshot_count = 0
    if manifest_path.exists():
        for relative, sha in json.loads(manifest_path.read_text(encoding="utf-8")).items():
            path = (root / "implementation" / relative).resolve()
            require(
                path.is_relative_to((root / "implementation").resolve()), "snapshot path escape"
            )
            require(file_digest(path) == sha, "implementation snapshot changed")
            snapshot_count += 1
    return seal(
        output,
        {
            "reviewed_evidence_id": summary["evidence_id"],
            "reviewed_protocol_id": protocol["evidence_id"],
            "arithmetic_and_chain_passed": True,
            "reviewer_independent_of_author": False,
            "review_scope": "separate arithmetic implementation and read-only SQLite/source checks; same-author technical audit, not independent attestation",
            "checks": [
                "source_hashes",
                "split_denominators",
                "daily_cost_pnl",
                "compound_drawdown",
                "sqlite_attempts",
                "frozen_selection",
                "all_cost_delay_assessments",
            ],
            "valid_slots_recomputed": evaluated,
            "attempt_states": dict(states),
            "snapshot_files_checked": snapshot_count,
            "feedback_evaluations": sum(
                r["ledger"].get("evaluation_calls", 0)
                for r in runs
                if r["method"] == "feedback_agent"
            ),
            "measured_cost_evidence_available": False,
            "independent_confirmation_available": False,
            "alpha_authority": False,
            "broker_authority": False,
            "independent_review_status": "AWAITING_EXTERNAL_ATTESTATION",
            "review_implementation_sha256": file_digest(Path(__file__)),
        },
        "us-r3-followup-review-",
    )


def evidence_plan(root: Path, output: Path) -> dict[str, Any]:
    protocol = _sealed(root / "protocol.json", "evidence_id", "us-r3-completion-protocol-")
    summary = _sealed(root / "summary.json", "evidence_id", "us-r3-completion-")
    require(summary["protocol_id"] == protocol["evidence_id"], "planning evidence chain mismatch")
    scenarios = []
    for family in (6, 72):
        for effect in (5.0, 10.0):
            d = EvidenceDesign(family_size=family, effect_bps=effect).to_dict()
            scenarios.append(
                {
                    **d,
                    "scope": "future design feasibility only; does not alter completed pilot thresholds",
                }
            )
    return seal(
        output,
        {
            "reviewed_evidence_id": summary["evidence_id"],
            "source_exposure": protocol["exposure_ledger"],
            "cost_inventory": protocol["cost_inventory"],
            "existing_protocol_design": protocol["design"],
            "future_design_scenarios": scenarios,
            "search_scope": "bound R2 source and explicitly inventoried project quote artifacts; no claim to inventory external accounts",
            "data_requirements": [
                {
                    "kind": "equity_quotes_and_trades",
                    "required": [
                        "instrument_type",
                        "event_time",
                        "available_at",
                        "bid",
                        "ask",
                        "size",
                        "venue",
                        "license",
                    ],
                    "status": "not_admitted",
                },
                {
                    "kind": "cost_observations",
                    "required": [
                        "fee_schedule",
                        "order_fill_time",
                        "reference_quote",
                        "fill_price",
                        "participation",
                        "instrument_mapping",
                    ],
                    "status": "not_admitted",
                },
                {
                    "kind": "pit_universe",
                    "required": [
                        "listing_delisting",
                        "corporate_actions",
                        "sector_as_of",
                        "availability_time",
                    ],
                    "status": "not_admitted",
                },
                {
                    "kind": "independent_sample",
                    "required": [
                        "pre_observation_admission",
                        "non_exposure",
                        "fixed_calendar",
                        "reviewer_receipt",
                    ],
                    "status": "not_admitted",
                },
            ],
            "next_mechanism_search_admitted": False,
            "decision": "no positive development candidate to confirm; repair tool adherence separately and admit relevant data before another mechanism experiment",
            "alpha_authority": False,
            "broker_authority": False,
        },
        "us-r3-evidence-plan-",
    )
