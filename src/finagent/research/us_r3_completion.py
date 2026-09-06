"""Bounded R3 pilot, frozen exploratory model, and explicit evidence closure.

No model sees a source path or nondevelopment returns. All real financial
results here remain exposed-data exploration. Missing final evidence is a
terminal, never an inferred positive confirmation.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from dataclasses import asdict
from pathlib import Path
from typing import Any, cast

from finagent.agents.r3_contracts import (
    DevelopmentRecord,
    DevelopmentScope,
    ResearchRuntimePolicy,
    canonical_json,
    decode_action,
    identity,
    proposal_action,
)
from finagent.agents.r3_provider import TARIFF, StrictDeepSeekProvider
from finagent.agents.r3_runtime import (
    ResearchCapabilityRuntime,
    ResearchProvider,
    implementation_id,
)
from finagent.research.us_a1_factor_graph import FactorExpectedDirection, FactorGraphSpec
from finagent.research.us_a1_factor_materialization import compile_factor_graph_batch
from finagent.research.us_a1_factor_panel_materialization import materialize_compiled_factor_panel
from finagent.research.us_a1_factor_validation import validate_factor_graph
from finagent.research.us_r3_alpha_catalog import build_us_r3_executable_frontier_candidates
from finagent.research.us_r3_economic_campaign import (
    _calendar,
    _sealed,
    aligned_session,
    code_identity,
    digest,
    file_digest,
)
from finagent.research.us_r3_economics import (
    EconomicPolicy,
    positive_weights,
    simulate_session,
    summarize_sessions,
)
from finagent.research.us_r3_inference import (
    EvidenceDesign,
    confirmation_terminal,
    describe_returns,
    purged_splits,
)
from finagent.research.us_r3_usability import write_immutable_json

METHODS = ("manual", "programmatic", "blind_llm", "feedback_agent")
SLOTS = 3
RUNS = 3
AUTHORITY = {
    "alpha_authority": False,
    "independent_confirmation": False,
    "broker_authority": False,
    "live_capital_authority": False,
}


def completion_code() -> str:
    root = Path(__file__).parents[1]
    return str(
        digest(
            {
                "economic": code_identity(),
                "runtime": implementation_id(),
                **{
                    name: file_digest(root / name)
                    for name in (
                        "research/us_r3_completion.py",
                        "research/us_r3_inference.py",
                        "research/us_r3_confirmation.py",
                        "agents/r3_provider.py",
                    )
                },
            }
        )
    )


def seal(path: Path, document: dict[str, Any], prefix: str) -> dict[str, Any]:
    payload = {**document, "evidence_id": prefix + digest(document)}
    write_immutable_json(path, payload)
    return payload


def freeze_completion(economic_protocol: Path, config: Path, output: Path) -> dict[str, Any]:
    economic = _sealed(economic_protocol, "protocol_id", "us-r3-economic-protocol-")
    if economic["implementation_id"] != code_identity():
        raise ValueError("economic source binding must be frozen under current economic code")
    for item in economic["inputs"].values():
        if file_digest(Path(item["path"])) != item["sha256"]:
            raise ValueError("economic source binding changed")
    from finagent.agents.providers.config import load_llm_profile

    profile = load_llm_profile(config)
    if (profile.provider, profile.model, profile.base_url.rstrip("/")) != (
        "deepseek",
        "deepseek-v4-pro",
        "https://api.deepseek.com",
    ):
        raise ValueError("provider routing is not admitted by the frozen tariff")
    design = EvidenceDesign()
    policy = ResearchRuntimePolicy(
        maximum_slots=SLOTS,
        maximum_attempts=12,
        maximum_attempts_per_slot=4,
        maximum_evaluations=SLOTS,
        maximum_tokens=120000,
        tokens_per_call=16384,
        maximum_cost_microusd=250000,
        cost_per_call_microusd=50000,
        call_timeout_seconds=45.0,
    )
    costs = []
    repository = Path(__file__).parents[3]
    for relative, classification in (
        (
            "reports/us_instruments/us_i0_delayed_reference_quotes_fbc3da92fc83e7cb86a04c9d.json",
            "delayed CFD simulation reference; not 2025 executable equity spreads",
        ),
        (
            "reports/us_instruments/us_i0_target_broker_quotes.json",
            "target inventory only; no historical fill/slippage admission",
        ),
        (
            "reports/mt5/mt5_fx_continuous_quote_smoke.json",
            "FX transport fixture; not US trading cost evidence",
        ),
    ):
        path = repository / relative
        costs.append(
            {
                "artifact": relative,
                "present": path.exists(),
                "sha256": file_digest(path) if path.exists() else None,
                "scope": classification,
                "admitted_for_historical_cost": False,
            }
        )
    payload = {
        "schema_version": "finagent.us-r3-completion-protocol.v1",
        "implementation_id": completion_code(),
        "economic_protocol": {
            "path": str(economic_protocol.resolve()),
            "sha256": file_digest(economic_protocol),
        },
        "config": {"path": str(config.resolve()), "sha256": file_digest(config)},
        "profile": {
            "provider": profile.provider,
            "model": profile.model,
            "base_url": profile.base_url,
        },
        "source_admission": "trusted local R2 version/hash/calendar lineage for development only; no upstream reauthentication or independent evidence",
        "exposure_ledger": [
            {
                "source": "R2 2006-2026 corpus",
                "status": "previously_exposed",
                "usable_for_confirmation": False,
            },
            {
                "source": "prospective post-model-freeze observations",
                "status": "not_available_or_admitted",
                "usable_for_confirmation": False,
            },
        ],
        "cost_inventory": costs,
        "measured_spread": None,
        "measured_slippage": None,
        "measured_fees": None,
        "cost_policy": "primary 5bp per gross net-traded notional; stress 0/1/10bp and two-bar delay; all assumptions",
        "design": design.to_dict(),
        "splits": purged_splits(economic["sessions"]),
        "split_scope": "all splits globally exposed; temporal development/validation/outer access discipline, not restored independence",
        "methods": list(METHODS),
        "runs_per_method": RUNS,
        "slots_per_run": SLOTS,
        "runtime_policy": asdict(policy),
        "provider_tariff": TARIFF,
        "maximum_external_cost_microusd": 2 * RUNS * policy.maximum_cost_microusd,
        "proposal_rule": "positive graph direction only; graph outputs cross-section demeaned; positive top five; unchanged 60m rolling sleeves",
        "search_budget": "36 slots including invalid/duplicate/failed slots; no replacement or repair outside per-slot attempts; all twelve run results retained",
        "selection_rule": "per run select maximum complete development 5bp net return, candidate-ID tie break; cash unless strictly positive; freeze membership before validation/outer evaluation",
        "inference_family": "36 slots times two primary endpoints; descriptive HAC and block bootstrap; failed slots remain denominator",
        "pilot_superiority_rule": "descriptive paired run differences only; three runs cannot establish population superiority",
        "confirmation": "independent evidence absent; never read a final source without separate authenticated admission and independent review",
        **AUTHORITY,
    }
    return seal(output, payload, "us-r3-completion-protocol-")


class AdmittedEvaluator:
    """Trusted host only: source files never cross the model capability boundary."""

    def __init__(
        self, economic: dict[str, Any], days: list[str], cache_root: Path, scope_id: str
    ) -> None:
        self.economic, self.days, self.cache_root, self.scope_id = (
            economic,
            days,
            cache_root,
            scope_id,
        )
        self.source_id = identity(economic["inputs"]["source"], "r3-admitted-source")
        self.evaluator_id = identity(
            {"protocol": economic["protocol_id"], "days": days, "code": completion_code()},
            "r3-net-evaluator",
        )
        self.frames: list[tuple[str, Any, Any]] = []
        self.calls = 0

    def _frames(self) -> list[tuple[str, Any, Any]]:
        if self.frames:
            return self.frames
        from datetime import UTC, datetime, timedelta

        import duckdb

        from finagent.research.us_r3_usability import FEATURE_QUERY, _session_assets

        source = Path(self.economic["inputs"]["source"]["path"])
        if file_digest(source) != self.economic["inputs"]["source"]["sha256"]:
            raise ValueError("admitted source changed")
        calendar = {
            s.session_date.isoformat(): s
            for s in _calendar(Path(self.economic["inputs"]["calendar"]["path"])).sessions
        }
        with duckdb.connect(config={"memory_limit": "256MiB", "threads": "1"}) as connection:
            for day in self.days:
                query = (
                    FEATURE_QUERY.replace(
                        "WHERE slice_id = ?",
                        "WHERE slice_id = ? AND CAST(session_date AS VARCHAR) = ?",
                    )
                    + " LIMIT 16385"
                )
                feature_rows = connection.execute(
                    query, [str(source), "decay_15m_30m", day]
                ).fetchall()
                if not feature_rows or len(feature_rows) > 16384:
                    raise ValueError("missing or unbounded feature session")
                raw = _session_assets(feature_rows)
                execution = connection.execute(
                    "SELECT research_asset_id, epoch(available_at), epoch(source_available_at), source_price FROM read_parquet(?) WHERE slice_id='frequency_5m_60m' AND CAST(session_date AS VARCHAR)=? LIMIT 49153",
                    [str(source), day],
                ).fetchall()
                if len(execution) > 49152:
                    raise ValueError("unbounded reference session")
                marks = {}
                for asset, available, observed, price in execution:
                    key = (asset, datetime.fromtimestamp(available, UTC))
                    if (
                        key in marks
                        or (price is None) != (observed is None)
                        or (
                            price is not None
                            and (observed != available or not math.isfinite(price) or price <= 0)
                        )
                    ):
                        raise ValueError("invalid causal execution reference")
                    marks[key] = price
                assets = aligned_session(raw, calendar[day], self.economic["universe"])
                clocks = [
                    calendar[day].open_at + timedelta(minutes=5 * (i + 1))
                    for i in range(calendar[day].regular_minutes // 5)
                ]
                prices = [
                    {a.asset_id: marks.get((a.asset_id, clock)) for a in assets} for clock in clocks
                ]
                self.frames.append((day, assets, prices))
        if [d for d, _, _ in self.frames] != self.days:
            raise ValueError("missing scheduled evaluator session")
        return self.frames

    def calculate(
        self,
        graph: FactorGraphSpec | None,
        *,
        cost: float = 5.0,
        delay: int = 1,
        equal_weight: bool = False,
    ) -> dict[str, Any]:
        candidate = "equal_weight" if equal_weight else "cash"
        if graph is not None:
            validation = validate_factor_graph(graph)
            if not validation.valid or validation.canonicalization is None:
                raise ValueError("invalid evaluator graph")
            candidate = validation.canonicalization.candidate_id
        key = identity(
            {"candidate": candidate, "cost": cost, "delay": delay, "evaluator": self.evaluator_id},
            "r3-candidate-evaluation",
        )
        path = self.cache_root / (key + ".json")
        if path.exists():
            cached = _sealed(path, "evidence_id", "r3-evaluation-")
            if cached["cache_key"] != key or cached["evaluator_id"] != self.evaluator_id:
                raise ValueError("evaluation cache binding mismatch")
            return cached
        self.calls += 1
        compiled = (
            compile_factor_graph_batch((graph,), admit_panel_operators=True)
            if graph is not None
            else None
        )
        policy = EconomicPolicy(execution_profile="pending_exit_5m", delay_bars=delay)
        daily = []
        behavior = hashlib.sha256()
        concentration = []
        for day, assets, prices in self._frames():
            series = {}
            if compiled is not None:
                panel = materialize_compiled_factor_panel(
                    compiled, assets, minimum_cross_section=policy.minimum_breadth
                )
                series = {row.asset_id: row.values for row in panel.candidates}
            targets = []
            for i in range(len(assets[0].bars)):
                scores = {
                    a.asset_id: series[a.asset_id][i]
                    if compiled is not None
                    else (1.0 if equal_weight and a.bars[i].is_complete else None)
                    for a in assets
                }
                valid = [v for v in scores.values() if v is not None]
                mean = math.fsum(valid) / len(valid) if valid else 0.0
                centered = {
                    a: v - mean if v is not None and compiled is not None else v
                    for a, v in scores.items()
                }
                targets.append(positive_weights(centered, policy, equal_weight=equal_weight))
            result = simulate_session(prices, targets, policy, cost_bps=cost)
            for row in cast(list[dict[str, Any]], result["ledger"]):
                behavior.update(
                    canonical_json(
                        {"date": day, "bar": row["bar_index"], "trades": row["net_trades"]}
                    ).encode()
                )
                marks = prices[row["bar_index"]]
                values = [
                    q * marks[a] for a, q in row["shares"].items() if marks.get(a) is not None
                ]
                if len(values) == len(row["shares"]) and values and sum(values) > 0:
                    concentration.append(sum((v / sum(values)) ** 2 for v in values))
            result.pop("ledger")
            daily.append({"session_date": day, **result})
        return seal(
            path,
            {
                "candidate_id": candidate,
                "cache_key": key,
                "evaluator_id": self.evaluator_id,
                "cost_bps": cost,
                "delay_bars": delay,
                "daily": daily,
                "summary": summarize_sessions(daily),
                "behavior_id": behavior.hexdigest(),
                "mean_invested_hhi": math.fsum(concentration) / len(concentration)
                if concentration
                else None,
                "sector_exposure": None,
                "sector_scope": "PIT sector mapping not admitted",
                **AUTHORITY,
            },
            "r3-evaluation-",
        )

    def evaluate(self, graph: FactorGraphSpec) -> DevelopmentRecord:
        result = self.calculate(graph)
        summary = result["summary"]
        if not summary["full_period_evaluable"]:
            raise ValueError("incomplete development economics")
        return DevelopmentRecord(
            self.scope_id,
            self.source_id,
            "evaluation",
            canonical_json(
                {
                    "candidate_id": result["candidate_id"],
                    "evaluator_id": self.evaluator_id,
                    "metrics": {
                        "net_return_bps": summary["compounded_return"] * 10000,
                        "turnover": summary["resolved_session_gross_traded_sum"],
                        "valid_count": len(self.days),
                    },
                }
            ),
        )


def baseline_action(method: str, run: int, slot: int) -> str:
    candidates = build_us_r3_executable_frontier_candidates()
    candidate = candidates[slot]
    action = json.loads(proposal_action(candidate.graph, candidate.hypothesis))
    if method == "programmatic":
        rng = random.Random(101 + run * 17 + slot)
        for node in action["arguments"]["nodes"]:
            if "window_bars" in node:
                node["window_bars"] = rng.choice((2, 3, 4, 6, 8))
        action["arguments"]["hypothesis"]["summary"] = (
            "Frozen seeded grammar baseline; no outcome-dependent tuning"
        )
    return str(canonical_json(action))


def run_completion(
    protocol_path: Path, root: Path, *, provider_factory: Any = None, progress: Any = None
) -> dict[str, Any]:
    protocol = _sealed(protocol_path, "evidence_id", "us-r3-completion-protocol-")
    if protocol["implementation_id"] != completion_code():
        raise ValueError("completion implementation changed; refreeze")
    for name in ("economic_protocol", "config"):
        if file_digest(Path(protocol[name]["path"])) != protocol[name]["sha256"]:
            raise ValueError("bound completion input changed")
    economic = _sealed(
        Path(protocol["economic_protocol"]["path"]), "protocol_id", "us-r3-economic-protocol-"
    )
    for item in economic["inputs"].values():
        if file_digest(Path(item["path"])) != item["sha256"]:
            raise ValueError("bound economic input changed")
    write_immutable_json(root / "protocol.json", protocol)
    terminal_path = root / "summary.json"
    if terminal_path.exists():
        saved = _sealed(terminal_path, "evidence_id", "us-r3-completion-")
        if saved["protocol_id"] != protocol["evidence_id"]:
            raise ValueError("completion report binding mismatch")
        model = _sealed(root / "frozen_model.json", "evidence_id", "r3-frozen-model-")
        runs = [
            _sealed(root / "runs" / f"{method}-{run}.json", "evidence_id", "r3-pilot-run-")
            for method in METHODS
            for run in range(RUNS)
        ]
        if (
            model["evidence_id"] != saved["frozen_model_id"]
            or [r["evidence_id"] for r in runs] != saved["run_evidence_ids"]
            or model["run_evidence_ids"] != saved["run_evidence_ids"]
        ):
            raise ValueError("completion evidence chain mismatch")
        return {**saved, "resumed": True}
    scope_id = "r3-pilot-development"
    evaluator = AdmittedEvaluator(
        economic, protocol["splits"]["development"], root / "development", scope_id
    )
    scope = DevelopmentScope(
        scope_id,
        (
            DevelopmentRecord(
                scope_id,
                evaluator.source_id,
                "coverage",
                canonical_json(
                    {"row_count": len(evaluator.days), "available_count": len(evaluator.days)}
                ),
            ),
        ),
        evaluator.source_id,
        evaluator.evaluator_id,
    )
    example = baseline_action("manual", 0, 0)
    instruction = (
        "You are proposing a falsifiable intraday factor within a fixed research pilot. Return one JSON action only. "
        "Only POSITIVE direction is admitted; encode any reversal with NEGATE. Use dimensionless output. "
        "Do not submit raw prices/volume. Each slot must end with submit_factor. If evaluation tools are allowed: "
        "first validate_factor, then evaluate_development using the returned candidate ID, then submit the identical proposal_action supplied in feedback. "
        "If evaluation is unavailable, submit directly. Retain meaningful mechanism and falsification text; do not claim profitability. "
        "A wire-format example (do not copy its factor): " + example
    )
    rows = []
    real = provider_factory is None
    for method in METHODS:
        for run in range(RUNS):
            run_id = f"{method}-{run}"
            path = root / "runs" / (run_id + ".json")
            if path.exists():
                row = _sealed(path, "evidence_id", "r3-pilot-run-")
                if row["protocol_id"] != protocol["evidence_id"]:
                    raise ValueError("run binding mismatch")
                rows.append(row)
                continue
            actions: list[str | None] = []
            ledger: dict[str, Any] = {}
            if method in ("manual", "programmatic"):
                actions = [baseline_action(method, run, slot) for slot in range(SLOTS)]
            else:
                provider: ResearchProvider = (
                    provider_factory(method, run)
                    if provider_factory
                    else StrictDeepSeekProvider(Path(protocol["config"]["path"]), instruction)
                )
                policy = ResearchRuntimePolicy(
                    **{**protocol["runtime_policy"], "feedback_enabled": method == "feedback_agent"}
                )
                runtime = ResearchCapabilityRuntime(
                    root / "ledgers" / (run_id + ".sqlite"),
                    run_id=run_id,
                    scope=scope,
                    provider=provider,
                    provider_id="deepseek-official" if real else "synthetic-provider",
                    model_id="deepseek-v4-pro" if real else "synthetic",
                    policy=policy,
                    evaluator=evaluator if method == "feedback_agent" else None,
                )
                for slot in range(SLOTS):
                    selected = None
                    for attempt in range(policy.maximum_attempts_per_slot):
                        reply = runtime.step(f"slot-{slot}-attempt-{attempt}", slot)
                        if progress:
                            progress(
                                "pilot_step",
                                {
                                    "run": run_id,
                                    "slot": slot,
                                    "attempt": attempt,
                                    "outcome": reply.get("outcome"),
                                },
                            )
                        if reply.get("outcome") == "SUBMITTED":
                            selected = runtime.ledger.proposal(reply["candidate_id"])
                            break
                        if reply.get("outcome") in ("DUPLICATE", "SLOT_CLOSED"):
                            break
                    actions.append(selected)
                ledger = runtime.ledger.snapshot()
            slots = []
            for slot, raw in enumerate(actions):
                try:
                    action = decode_action(raw or "")
                    proposal = action.proposal
                    if proposal is None or proposal.direction != FactorExpectedDirection.POSITIVE:
                        raise ValueError("unsupported hypothesis direction")
                    hypothesis = proposal.hypothesis()
                    result = evaluator.calculate(proposal.graph)
                    slots.append(
                        {
                            "slot": slot,
                            "valid": True,
                            "action": raw,
                            "candidate_id": hypothesis.candidate_id,
                            "mechanism_fidelity": "explicit falsification contract validated; empirical causal story unverified",
                            "evaluation": result,
                        }
                    )
                except (ValueError, TypeError):
                    slots.append(
                        {
                            "slot": slot,
                            "valid": False,
                            "reason": "INVALID_OR_UNSUBMITTED",
                            "action": raw,
                        }
                    )
            row = seal(
                path,
                {
                    "protocol_id": protocol["evidence_id"],
                    "method": method,
                    "run": run,
                    "slots": slots,
                    "ledger": ledger,
                    "provider_calls_are_real": real and method in ("blind_llm", "feedback_agent"),
                    **AUTHORITY,
                },
                "r3-pilot-run-",
            )
            rows.append(row)
            if progress:
                progress("pilot_run_complete", {"run": run_id})
    # Freeze membership and selection before accessing validation/outer returns.
    members = []
    for row in rows:
        eligible = [
            s
            for s in row["slots"]
            if s["valid"]
            and s["evaluation"]["summary"]["full_period_evaluable"]
            and s["evaluation"]["summary"]["compounded_return"] > 0
        ]
        best = sorted(
            eligible,
            key=lambda s: (-s["evaluation"]["summary"]["compounded_return"], s["candidate_id"]),
        )
        members.append(
            {
                "method": row["method"],
                "run": row["run"],
                "candidate_id": best[0]["candidate_id"] if best else "cash",
                "action": best[0]["action"] if best else None,
            }
        )
    from datetime import UTC, datetime

    freeze_time = datetime.now(UTC).isoformat()
    if (root / "frozen_model.json").exists():
        freeze_time = _sealed(root / "frozen_model.json", "evidence_id", "r3-frozen-model-")[
            "frozen_at_utc"
        ]
    frozen_model = seal(
        root / "frozen_model.json",
        {
            "protocol_id": protocol["evidence_id"],
            "run_evidence_ids": [r["evidence_id"] for r in rows],
            "members": members,
            "frozen_at_utc": freeze_time,
            "selection": protocol["selection_rule"],
            **AUTHORITY,
        },
        "r3-frozen-model-",
    )
    design = EvidenceDesign()
    assessments = []
    for partition in ("validation", "outer_exploratory"):
        judge = AdmittedEvaluator(
            economic, protocol["splits"][partition], root / partition, "not-model-accessible"
        )
        control = judge.calculate(None, equal_weight=True)
        for member in members:
            member_action = decode_action(member["action"]) if member["action"] else None
            graph = (
                member_action.proposal.graph if member_action and member_action.proposal else None
            )
            grid = {str(cost): judge.calculate(graph, cost=cost) for cost in (0.0, 1.0, 5.0, 10.0)}
            stress = judge.calculate(graph, delay=2)
            returns = [d["net_return"] for d in grid["5.0"]["daily"]]
            excess = [
                a["net_return"] - b["net_return"]
                if a["net_return"] is not None and b["net_return"] is not None
                else None
                for a, b in zip(grid["5.0"]["daily"], control["daily"], strict=True)
            ]
            assessments.append(
                {
                    "partition": partition,
                    "method": member["method"],
                    "run": member["run"],
                    "candidate_id": member["candidate_id"],
                    "cost_summaries": {k: v["summary"] for k, v in grid.items()},
                    "two_bar_delay": stress["summary"],
                    "inference": describe_returns(returns, design),
                    "paired_equal_weight_inference": describe_returns(excess, design, paired=True),
                    "mean_invested_hhi": grid["5.0"]["mean_invested_hhi"],
                    "paired_equal_weight_mean_bps": math.fsum(
                        a["net_return"] - b["net_return"]
                        for a, b in zip(grid["5.0"]["daily"], control["daily"], strict=True)
                    )
                    / len(returns)
                    * 10000
                    if all(
                        d["net_return"] is not None for d in grid["5.0"]["daily"] + control["daily"]
                    )
                    else None,
                }
            )
    valid = [s for r in rows for s in r["slots"] if s["valid"]]
    comparisons = []
    for method in METHODS:
        method_rows = [r for r in rows if r["method"] == method]
        method_valid = [s for r in method_rows for s in r["slots"] if s["valid"]]
        comparisons.append(
            {
                "method": method,
                "slots": RUNS * SLOTS,
                "valid_slots": len(method_valid),
                "unique_structures": len({s["candidate_id"] for s in method_valid}),
                "unique_behaviors": len({s["evaluation"]["behavior_id"] for s in method_valid}),
                "all_run_outer_returns": [
                    a["cost_summaries"]["5.0"]["compounded_return"]
                    for a in assessments
                    if a["method"] == method and a["partition"] == "outer_exploratory"
                ],
                "charged_cost_upper_microusd": sum(
                    r["ledger"].get("charged_cost_microusd", 0) for r in method_rows
                ),
            }
        )
    final = confirmation_terminal(
        admitted=False,
        independent_review_id=None,
        effective_sessions=None,
        minimum_sessions=cast(int, design.to_dict()["minimum_effective_sessions"]),
        statistical_pass=False,
        economic_pass=False,
    )
    return seal(
        terminal_path,
        {
            "protocol_id": protocol["evidence_id"],
            "frozen_model_id": frozen_model["evidence_id"],
            "slot_denominator": len(rows) * SLOTS,
            "valid_slots": len(valid),
            "unique_structures": len({s["candidate_id"] for s in valid}),
            "unique_behaviors": len({s["evaluation"]["behavior_id"] for s in valid}),
            "run_evidence_ids": [r["evidence_id"] for r in rows],
            "assessments": assessments,
            "method_comparisons": comparisons,
            "provider_run_statuses": {
                f"{r['method']}-{r['run']}": r["ledger"].get("status")
                for r in rows
                if r["method"] in ("blind_llm", "feedback_agent")
            },
            "real_pilot_has_valid_submissions_in_every_run": real
            and all(
                any(s["valid"] for s in r["slots"])
                for r in rows
                if r["method"] in ("blind_llm", "feedback_agent")
            ),
            "external_model_called": any(
                r["provider_calls_are_real"] and r["ledger"].get("attempt_count", 0) for r in rows
            ),
            "charged_cost_upper_microusd": sum(
                r["ledger"].get("charged_cost_microusd", 0) for r in rows
            ),
            "pilot_scope": "three matched runs per method; manual control repeated, not three independent human researchers; no population superiority claim",
            "confirmation_terminal": final,
            "terminal": "EXPLORATORY_RESEARCH_COMPLETE_INDEPENDENT_EVIDENCE_UNAVAILABLE",
            "sector_capacity_evidence": "unavailable; no historical PIT sector/quote/impact admission",
            **AUTHORITY,
        },
        "us-r3-completion-",
    )
