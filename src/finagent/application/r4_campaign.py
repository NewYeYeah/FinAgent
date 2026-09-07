"""Explicit operator freeze/verify and scheduling over existing research services."""

from __future__ import annotations

import json
import sqlite3
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import partial
from importlib.metadata import version as package_version
from pathlib import Path
from typing import Any

from finagent.agents.audit import SQLiteAgentAuditStore
from finagent.agents.r3_contracts import (
    ResearchRuntimePolicy,
    canonical_json,
    identity,
)
from finagent.agents.r3_ledger import ResearchLedger
from finagent.agents.r3_runtime import ResearchProvider, _bounded_call
from finagent.agents.r4_contracts import ALLOCATORS, AUTHORITY
from finagent.agents.r4_provider_admission import (
    AdmittedDeepSeekProvider,
    ProviderAdmission,
    provider_binding,
)
from finagent.application.research_controller import open_research_session, run_research_session
from finagent.application.research_controller_host import R4ResearchAdmission, R4ResearchHost
from finagent.research.r4_campaign_protocol import (
    AdaptiveStrategySpec,
    R4MatchedComparisonProtocol,
    assess_campaign,
    matched_protocol,
)
from finagent.research.us_r3_economic_campaign import file_digest
from finagent.research.us_r3_usability import write_immutable_json


def campaign_implementation() -> dict[str, str]:
    root = Path(__file__).resolve().parents[3]
    # All tracked executable code and dependency intents, including the operator.
    # Freeze JSON/docs are deliberately outside their own content digest.
    files = subprocess.check_output(
        [
            "git",
            "ls-files",
            "src",
            "scripts",
            "workspace/src",
            "pyproject.toml",
            "uv.lock",
            "workspace/package-lock.json",
        ],
        cwd=root,
        text=True,
    ).splitlines()
    # New files must be included before the first commit as well.
    files = sorted(
        set(files)
        | {str(p.relative_to(root)).replace("\\", "/") for p in (root / "src").rglob("*.py")}
        | {"scripts/r4_campaign.py"}
    )
    return {name: file_digest(root / name) for name in files if (root / name).is_file()}


def campaign_environment() -> dict[str, str]:
    return {
        "sqlite": sqlite3.sqlite_version,
        **{n: package_version(n) for n in ("httpx", "ag-ui-protocol", "pydantic")},
    }


@dataclass(frozen=True)
class R4CampaignFreeze:
    payload_json: str

    def to_dict(self) -> dict[str, Any]:
        return dict(json.loads(self.payload_json))

    @property
    def freeze_id(self) -> str:
        return identity(self.to_dict(), "r4-campaign-freeze")

    @property
    def protocol(self) -> R4MatchedComparisonProtocol:
        return R4MatchedComparisonProtocol(canonical_json(self.to_dict()["protocol"]))


def freeze_campaign(
    admission: R4ResearchAdmission,
    provider: ProviderAdmission,
    output: Path,
    *,
    version: str = "r4-matched-v3",
    fixture: bool = False,
    config: Path | None = None,
) -> R4CampaignFreeze:
    if output.exists() and any(output.iterdir()):
        raise ValueError(
            "freeze requires a fresh directory; financial/provider/trial outputs cannot predate freeze"
        )
    manifest = admission.manifest()
    admission.source.verify_unchanged()
    if not fixture and config is None:
        raise ValueError("explicit provider config required for real freeze")
    actual_binding = provider.to_dict()["binding"]
    if not fixture:
        assert config is not None
        actual_binding = provider_binding(config)
    provider.verify(actual_binding, fixture=fixture)
    synthetic = admission.source.identity.source_id.startswith("synthetic")
    if fixture != synthetic:
        raise ValueError(
            "real freeze requires real development source; fixture admission cannot grant campaign authority"
        )
    at = datetime.now(UTC).isoformat()
    research_id = identity(manifest, "r4-research-admission")
    protocol = matched_protocol(
        version=version,
        frozen_at=at,
        provider_admission_id=provider.admission_id,
        research_admission_id=research_id,
        initial_factor_ids=[f["factor_id"] for f in manifest["initial_factors"]],
        folds=manifest["folds"],
    )
    freeze = R4CampaignFreeze(
        canonical_json(
            {
                "schema_version": "finagent.r4-campaign-freeze.v1",
                "frozen_at": at,
                "status": "ACCEPTED_FIXTURE" if fixture else "ACCEPTED",
                "fixture_only": fixture,
                "provider_admission": provider.to_dict(),
                "provider_admission_id": provider.admission_id,
                "research_admission": manifest,
                "research_admission_id": research_id,
                "protocol": protocol.to_dict(),
                "protocol_id": protocol.protocol_id,
                "implementation": campaign_implementation(),
                "environment": campaign_environment(),
                "campaign_executed": False,
                "r4_stage_exit": False,
                **AUTHORITY,
            }
        )
    )
    if output.exists() and any(output.iterdir()):
        raise ValueError("output appeared before freeze")
    write_immutable_json(
        output / "campaign_freeze.json",
        {"campaign_freeze_id": freeze.freeze_id, **freeze.to_dict()},
    )
    return freeze


def verify_campaign(
    output: Path,
    admission: R4ResearchAdmission,
    provider: ProviderAdmission,
    *,
    accepted_freeze_id: str,
    config: Path | None = None,
    fixture: bool = False,
) -> R4CampaignFreeze:
    path = output / "campaign_freeze.json"
    if not path.is_file():
        raise ValueError("accepted campaign freeze required before execution")
    row = json.loads(path.read_text())
    recorded_id = row.pop("campaign_freeze_id")
    freeze = R4CampaignFreeze(canonical_json(row))
    if freeze.freeze_id != recorded_id or freeze.freeze_id != accepted_freeze_id:
        raise ValueError("campaign freeze identity mismatch")
    if (
        row["status"] != ("ACCEPTED_FIXTURE" if fixture else "ACCEPTED")
        or row["fixture_only"] != fixture
    ):
        raise ValueError("campaign admission not accepted for this execution")
    actual_binding = (
        provider.to_dict()["binding"] if fixture else provider_binding(config) if config else None
    )
    if actual_binding is None:
        raise ValueError("explicit provider config required")
    provider.verify(actual_binding, fixture=fixture)
    admission.source.verify_unchanged()
    if (
        row["provider_admission"] != provider.to_dict()
        or row["research_admission"] != json.loads(canonical_json(admission.manifest()))
        or row["implementation"] != campaign_implementation()
        or row["environment"] != campaign_environment()
    ):
        raise ValueError("campaign code/input/provider admission drift")
    protocol = matched_protocol(
        version=row["protocol"]["protocol_version"],
        frozen_at=row["frozen_at"],
        provider_admission_id=provider.admission_id,
        research_admission_id=identity(admission.manifest(), "r4-research-admission"),
        initial_factor_ids=row["protocol"]["initial_factor_ids"],
        folds=row["research_admission"]["folds"],
    )
    if row["protocol"] != protocol.to_dict() or row["protocol_id"] != protocol.protocol_id:
        raise ValueError("unsupported or mutated frozen protocol")
    if any(row[k] != v for k, v in AUTHORITY.items()):
        raise ValueError("campaign authority mismatch")
    return freeze


def runtime_policy(budget: dict[str, Any]) -> ResearchRuntimePolicy:
    return ResearchRuntimePolicy(
        maximum_attempts=budget["tool_calls"],
        maximum_attempts_per_slot=budget["tool_calls"],
        maximum_evaluations=budget["factor_evaluations"] + budget["portfolio_evaluations"],
        maximum_tokens=budget["total_tokens"],
        tokens_per_call=32768,
        maximum_cost_microusd=budget["cost_microusd"],
        cost_per_call_microusd=50000,
        maximum_run_seconds=budget["wall_clock_seconds"],
        call_timeout_seconds=120,
    )


def record_blocked_freeze(
    admission: R4ResearchAdmission,
    probe_directory: Path,
    output: Path,
    *,
    config: Path,
    version: str = "r4-matched-v3-blocked-provider",
) -> R4CampaignFreeze:
    """Retain the exact design and failed probe lineage without accepting execution."""
    if output.exists() and any(output.iterdir()):
        raise ValueError("blocked freeze requires a fresh directory")
    failure = json.loads((probe_directory / "failure.json").read_text())
    request = json.loads((probe_directory / "probe_request.json").read_text())
    if (
        failure.get("status") != "PROVIDER_ADMISSION_FAILED"
        or request.get("research_history") is not False
    ):
        raise ValueError("explicit non-research failed admission evidence required")
    admission.source.verify_unchanged()
    manifest = admission.manifest()
    at = datetime.now(UTC).isoformat()
    blocker = {
        "code": "VERIFIED_PROVIDER_ADMISSION_MISSING",
        "reason": failure["reason"],
        "phase": failure.get("phase", "not_recorded_in_original_probe"),
        "probe_request_digest": file_digest(probe_directory / "probe_request.json"),
        "probe_failure_digest": file_digest(probe_directory / "failure.json"),
        "probe_binding": request["binding"],
        "desired_binding": provider_binding(config),
        "probe_count": 1,
        "additional_probe_executed": False,
        "interpretation": "No accepted identity/usage receipt; do not infer credential, quota, response or cost verification from this failure.",
    }
    research_id = identity(manifest, "r4-research-admission")
    protocol = matched_protocol(
        version=version,
        frozen_at=at,
        provider_admission_id=identity(blocker, "unaccepted-provider"),
        research_admission_id=research_id,
        initial_factor_ids=[f["factor_id"] for f in manifest["initial_factors"]],
        folds=manifest["folds"],
    )
    freeze = R4CampaignFreeze(
        canonical_json(
            {
                "schema_version": "finagent.r4-campaign-freeze.v1",
                "frozen_at": at,
                "status": "BLOCKED_PROVIDER_ADMISSION",
                "fixture_only": False,
                "provider_admission": None,
                "provider_blocker": blocker,
                "research_admission": manifest,
                "research_admission_id": research_id,
                "protocol": protocol.to_dict(),
                "protocol_id": protocol.protocol_id,
                "implementation": campaign_implementation(),
                "environment": campaign_environment(),
                "campaign_executed": False,
                "r4_stage_exit": False,
                **AUTHORITY,
            }
        )
    )
    write_immutable_json(
        output / "campaign_freeze.json",
        {"campaign_freeze_id": freeze.freeze_id, **freeze.to_dict()},
    )
    return freeze


def _candidates(result: dict[str, Any], arm: str, run_id: str) -> list[dict[str, Any]]:
    if set(result["summary"]["arms"]) != set(ALLOCATORS):
        raise ValueError("all five deterministic comparators are mandatory")
    return [
        {
            "candidate_id": identity(
                {"run": run_id, "experiment": result["experiment_id"], "allocator": a},
                "r4-campaign-candidate",
            ),
            "run_id": run_id,
            "arm": arm,
            "experiment_id": result["experiment_id"],
            "factor_ids": result["factor_ids"],
            "allocator": a,
            "metrics": m,
            "runtime_agent_dependence": 0,
        }
        for a, m in result["summary"]["arms"].items()
    ]


def _deterministic(
    admission: R4ResearchAdmission,
    freeze: R4CampaignFreeze,
    output: Path,
    clock: Callable[[], float],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Fixed schedule, no provider. Existing ledger reserves each economic evaluation."""
    protocol = freeze.protocol.to_dict()
    ledger = ResearchLedger(
        output / "research.sqlite",
        run_id="deterministic",
        now=clock(),
        binding={
            "freeze_id": freeze.freeze_id,
            "schedule": protocol["primary"]["deterministic_factor_sets"],
        },
        policy=runtime_policy(protocol["primary"]["budgets"]),
    )
    host = R4ResearchHost(admission, output, "deterministic")
    candidates = []
    for i, ids in enumerate(protocol["primary"]["deterministic_factor_sets"]):
        reservation = ledger.reserve(f"deterministic-{i}", 0, now=clock(), provider_call=False)
        if reservation.result is not None:
            result = reservation.result
        else:
            experiment_id = identity(
                {"freeze": freeze.freeze_id, "factor_ids": ids}, "deterministic-experiment"
            )
            ledger.bind_action(
                reservation,
                {"tool": "evaluate_portfolio", "arguments": {"factor_ids": ids}},
                now=clock(),
            )
            ledger.bind_evaluation(reservation, experiment_id)
            if not ledger.active(reservation, now=clock(), evaluation=True):
                raise ValueError("deterministic evaluation budget denied")
            try:
                evaluated = _bounded_call(
                    partial(
                        host.evaluate_portfolio,
                        ids,
                        datetime.fromtimestamp(clock(), UTC),
                        experiment_id,
                    ),
                    ledger.policy.call_timeout_seconds,
                )
                if not ledger.active(reservation, now=clock()):
                    raise ValueError("deterministic evaluation exceeded deadline")
                result = ledger.finish(
                    reservation,
                    {
                        "outcome": "PORTFOLIO_EVALUATED",
                        "experiment_id": experiment_id,
                        "factor_ids": ids,
                        **evaluated,
                    },
                    tokens=0,
                    cost=0,
                )
            except Exception:  # noqa: BLE001 -- financial/infrastructure failures remain charged.
                ledger.finish(
                    reservation,
                    {"outcome": "TOOL_FAILED"},
                    tokens=0,
                    cost=0,
                    halt="CAMPAIGN_SYSTEM_FAILURE",
                )
                raise ValueError("deterministic evaluator infrastructure failure") from None
        if result["outcome"] != "PORTFOLIO_EVALUATED":
            raise ValueError("deterministic pending/failed evaluation; no replacement")
        candidates.extend(_candidates(result, "deterministic_selection", "deterministic"))
    return candidates, {
        **ledger.snapshot(),
        "llm_calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "factor_set_proposals": len(protocol["primary"]["deterministic_factor_sets"]),
        "factor_evaluations": 0,
        "portfolio_evaluations": ledger.snapshot()["evaluation_calls"],
    }


def run_campaign(
    output: Path,
    admission: R4ResearchAdmission,
    provider: ProviderAdmission,
    *,
    accepted_freeze_id: str,
    config: Path | None = None,
    fixture_provider_factory: Callable[[str], ResearchProvider] | None = None,
    clock: Callable[[], float] = time.time,
) -> dict[str, Any]:
    """Application scheduling only. This PR executes this path on fixtures exclusively."""
    fixture = fixture_provider_factory is not None
    freeze = verify_campaign(
        output,
        admission,
        provider,
        accepted_freeze_id=accepted_freeze_id,
        config=config,
        fixture=fixture,
    )
    if clock() < datetime.fromisoformat(freeze.to_dict()["frozen_at"]).timestamp():
        raise ValueError("campaign research clock cannot predate freeze")
    result_path = output / "campaign_result.json"
    if result_path.exists():
        result = dict(json.loads(result_path.read_text()))
        for name, digest in result["artifact_digests"].items():
            if file_digest(output / name) != digest:
                raise ValueError("committed campaign artifact drift")
        if result["campaign_result_id"] != identity(
            {k: v for k, v in result.items() if k != "campaign_result_id"}, "r4-campaign-result"
        ):
            raise ValueError("campaign result identity mismatch")
        return result
    protocol = freeze.protocol.to_dict()
    candidates: list[dict[str, Any]] = []
    completed: list[str] = []
    resources: dict[str, Any] = {}
    failure = False
    try:
        candidates, resources["deterministic"] = _deterministic(
            admission, freeze, output / "deterministic", clock
        )
        completed.append("deterministic")
        for run_id in protocol["runs"]:
            verify_campaign(
                output,
                admission,
                provider,
                accepted_freeze_id=accepted_freeze_id,
                config=config,
                fixture=fixture,
            )
            kind = "primary" if run_id.startswith("selection") else "discovery"
            arm = {
                "kind": kind,
                "freeze_id": freeze.freeze_id,
                "initial_factor_ids": protocol["initial_factor_ids"],
                "tools": protocol[kind]["tools"],
                "budgets": protocol[kind]["budgets"],
            }
            if not fixture_provider_factory and config is None:
                raise ValueError("explicit provider config required")
            transport = (
                fixture_provider_factory(run_id)
                if fixture_provider_factory
                else AdmittedDeepSeekProvider(config, provider)  # type: ignore[arg-type]
            )
            runtime = open_research_session(
                admission,
                output / run_id,
                run_id=run_id,
                objective=protocol["objective"],
                provider=transport,
                provider_id=provider.to_dict()["binding"]["provider_id"],
                model_id=provider.to_dict()["binding"]["model_id"],
                audit=SQLiteAgentAuditStore(output / run_id / "audit.sqlite"),
                policy=runtime_policy(arm["budgets"]),
                clock=clock,
                campaign_arm=arm,
            )
            started = time.monotonic()
            run_result = run_research_session(runtime)
            rows = runtime.ledger.journal()
            final = run_result["result"]
            verified_usage = not fixture and all(
                (r["result"] or {}).get("provider_usage") is not None
                for r in rows
                if r["context_json"] is not None
            )
            resources[run_id] = {
                **run_result["resources"],
                "wall_seconds": time.monotonic() - started,
                "llm_calls": sum(r["context_json"] is not None for r in rows),
                "input_tokens": sum(
                    (r["result"] or {}).get("provider_usage", {}).get("input_tokens", 0)
                    for r in rows
                )
                if verified_usage
                else None,
                "output_tokens": sum(
                    (r["result"] or {}).get("provider_usage", {}).get("output_tokens", 0)
                    for r in rows
                )
                if verified_usage
                else None,
                "attempt_outcomes": [r["state"] for r in rows],
                "usage_breakdown_verified": verified_usage,
                "research_resources": {
                    "proposal_slots": sum(
                        (r["action"] or {}).get("tool") in {"propose_factor", "validate_factor"}
                        for r in rows
                    ),
                    "factor_set_proposals": sum(
                        (r["action"] or {}).get("tool") == "propose_factor_set" for r in rows
                    ),
                    "untyped_rejections_debited_to_proposals": sum(
                        r["state"] == "REJECTED" and r["action"] is None for r in rows
                    ),
                    "factor_evaluations": sum(
                        bool(r["evaluation_reserved"])
                        and (r["action"] or {}).get("tool") == "evaluate_factor"
                        for r in rows
                    ),
                    "portfolio_evaluations": sum(
                        bool(r["evaluation_reserved"])
                        and (r["action"] or {}).get("tool") == "evaluate_portfolio"
                        for r in rows
                    ),
                },
            }
            for row in rows:
                if row["state"] == "PORTFOLIO_EVALUATED":
                    pool_candidates = _candidates(
                        row["result"],
                        "agent_selection" if kind == "primary" else "agent_discovery_exploratory",
                        run_id,
                    )
                    for candidate in pool_candidates:
                        candidate["agent_selected"] = (
                            final.get("outcome") == "DEVELOPMENT_CANDIDATE_PROPOSED"
                            and candidate["factor_ids"] == final["factor_set"]["factor_ids"]
                            and candidate["allocator"] == final["allocator"]["allocator"]
                            and candidate["experiment_id"] in final["experiment_ids"]
                        )
                    candidates.extend(pool_candidates)
            if run_result["terminal"] not in {
                "DEVELOPMENT_CANDIDATE_PROPOSED",
                "NO_CANDIDATE_RECOMMENDED",
                "RUN_BUDGET_EXHAUSTED",
                "TIME_BUDGET_EXHAUSTED",
                "SLOT_ATTEMPTS_EXHAUSTED",
            }:
                raise ValueError("campaign run system failure")
            completed.append(run_id)
    except Exception:  # noqa: BLE001 -- preserve ledgers and return host-owned failure, not exception secrets.
        failure = True
    assessment = assess_campaign(
        freeze.protocol,
        candidates,
        completed_runs=completed,
        system_failure=failure,
        resources=resources,
    )
    artifact_digests = {
        str(p.relative_to(output)).replace("\\", "/"): file_digest(p)
        for p in sorted(output.rglob("*"))
        if p.is_file() and p.name != "campaign_freeze.json"
    }
    result = {
        "campaign_freeze_id": freeze.freeze_id,
        "protocol_id": freeze.protocol.protocol_id,
        "completed_at": datetime.fromtimestamp(clock(), UTC).isoformat(),
        "fixture_only": fixture,
        "completed_runs": completed,
        "resources": resources,
        "candidates": candidates,
        "assessment": assessment,
        "artifact_digests": artifact_digests,
        **AUTHORITY,
    }
    result["campaign_result_id"] = identity(result, "r4-campaign-result")
    if assessment["candidate_id"] is not None:
        winner = next(c for c in candidates if c["candidate_id"] == assessment["candidate_id"])
        host = R4ResearchHost(admission, output / winner["run_id"], winner["run_id"])
        spec = AdaptiveStrategySpec.build(
            research_manifest=admission.manifest(),
            protocol_id=freeze.protocol.protocol_id,
            campaign_result_id=result["campaign_result_id"],
            candidate=winner,
            assessment=assessment,
            factor_definitions=[host.factor(f) for f in winner["factor_ids"]],
        )
        write_immutable_json(output / "development_candidate.json", json.loads(spec.payload_json))
    write_immutable_json(result_path, result)
    return result
