"""Trusted R4 host adapters over the existing numerical services and FactorLibrary."""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime
from importlib.metadata import version
from pathlib import Path
from platform import python_version
from typing import Any

from finagent.agents.r3_contracts import (
    ContractError,
    DevelopmentRecord,
    DevelopmentScope,
    FactorProposal,
    canonical_json,
    identity,
)
from finagent.agents.r4_contracts import AUTHORITY
from finagent.application.adaptive_portfolio import (
    allocation_implementation_ids,
    run_adaptive_portfolio,
)
from finagent.research.adaptive_factor_admission import (
    AdaptiveDevelopmentAdmission,
    FactorEvidenceMode,
    evidence_semantics,
)
from finagent.research.adaptive_inputs import DevelopmentPanelSource
from finagent.research.adaptive_walkforward import WalkForwardFold, validate_walkforward_layout
from finagent.research.factor_library import (
    FactorLibrary,
    FactorOrigin,
    FactorRegistration,
    FactorStatus,
)
from finagent.research.factor_library_evaluation import (
    FactorEvaluationConfig,
    evaluate_factor_library,
)
from finagent.research.factor_performance import NORMALIZATION, SUPPORT_RULE
from finagent.research.market_state import MarketStateRow, utc_text
from finagent.research.market_state_gmm import MarketStateModel
from finagent.research.r4_feedback import portfolio_feedback
from finagent.research.us_baselines import _canonical_hash
from finagent.research.us_r3_economic_campaign import file_digest
from finagent.research.us_r3_economics import EconomicPolicy
from finagent.research.us_r3_usability import write_immutable_json


@dataclass(frozen=True)
class R4ResearchAdmission:
    source: DevelopmentPanelSource
    folds: tuple[WalkForwardFold, ...]
    seed_library: Path
    economics: EconomicPolicy
    market_model: MarketStateModel
    market_snapshot: MarketStateRow
    scope: DevelopmentScope
    admitted_at: datetime

    def manifest(self) -> dict[str, Any]:
        library = FactorLibrary(self.seed_library, read_only=True)
        try:
            factors = tuple(FactorRegistration.from_dict(r) for r in library.list_factors())
            if any(
                datetime.fromisoformat(h["available_at"]) > self.admitted_at
                for r in library.list_factors()
                for h in r["lifecycle"]
            ):
                raise ValueError("seed lifecycle extends beyond admission")
        finally:
            library.close()
        validate_walkforward_layout(factors, self.folds, self.economics)
        if (
            any(f.created_at > self.admitted_at for f in factors)
            or max(f.evaluation.end for f in self.folds) > self.admitted_at
        ):
            raise ValueError("development scope not available at admission")
        if (
            self.market_model.source != self.source.identity
            or self.market_snapshot.model_id != self.market_model.model_id
            or self.market_snapshot.available_at > self.admitted_at
            or self.market_model.available_at > self.market_snapshot.available_at
            or self.market_model.available_at > self.folds[0].evaluation.start
        ):
            raise ValueError("market state admission mismatch")
        if (
            self.scope.evaluation_source_id != self.source.identity.identity
            or self.scope.evaluator_id is None
        ):
            raise ValueError("development evaluator source binding mismatch")
        return {
            "source": asdict(self.source.identity),
            "universe": list(self.source.universe),
            "calendar_id": self.source.calendar.calendar_id,
            "initial_factors": [f.to_dict() for f in factors],
            "initial_lifecycle": {r["factor_id"]: r["status"] for r in self._seed_rows()},
            "normalization_support": {"normalization": NORMALIZATION, "support_rule": SUPPORT_RULE},
            "execution_semantics": {
                "signal_clock": "15m",
                "delay_bars": 1,
                "holding_bars": 4,
                "schedule": "rolling_sleeves",
                "gross_exposure": "fixed_sleeve_budget; no_allocator_timing",
                "cost_bps": [0, 1, 5, 10],
                "cash": "existing_R3_positive_weights_missing_support_and_session_close",
            },
            "missing_fallback": "shared_support; unavailable sessions unresolved; positive_weights empty => cash; allocator unavailable quality => equal_weight",
            "input_bindings": dict(self.source.bindings),
            "seed_library": file_digest(self.seed_library),
            "folds": [f.to_dict() for f in self.folds],
            "economics": asdict(self.economics),
            "market_model": self.market_model.to_dict(),
            "market_snapshot": self.market_snapshot.to_dict(),
            "scope_id": self.scope.manifest_id,
            "evaluator_id": self.scope.evaluator_id,
            "evaluation_source_id": self.scope.evaluation_source_id,
            "admitted_at": utc_text(self.admitted_at),
            "implementation": allocation_implementation_ids(),
            "quality": {"lookback_sessions": 20, "minimum_observations": 5},
            "ridge_alpha": 1,
            "dependencies": {
                "python": python_version(),
                **{
                    name: version(name)
                    for name in ("numpy", "duckdb", "scikit-learn", "scipy", "threadpoolctl")
                },
            },
            **AUTHORITY,
        }

    def _seed_rows(self) -> list[dict[str, Any]]:
        library = FactorLibrary(self.seed_library, read_only=True)
        try:
            return list(library.list_factors())
        finally:
            library.close()


class R4ResearchHost:
    def __init__(self, admission: R4ResearchAdmission, output: Path, run_id: str) -> None:
        self.admission, self.output, self.run_id = admission, output, run_id
        self.manifest = admission.manifest()
        self.compatibility_id = identity(
            {
                k: self.manifest[k]
                for k in (
                    "source",
                    "input_bindings",
                    "folds",
                    "economics",
                    "quality",
                    "ridge_alpha",
                    "implementation",
                    "market_model",
                    "dependencies",
                )
            },
            "r4-comparison-scope",
        )
        self.library_path = output / "factor_library.sqlite"
        output.mkdir(parents=True, exist_ok=True)
        if not self.library_path.exists():
            shutil.copy2(admission.seed_library, self.library_path)
        self.admission.source.verify_unchanged()

    def verify(self) -> None:
        self.admission.source.verify_unchanged()
        if file_digest(self.admission.seed_library) != self.manifest["seed_library"]:
            raise ContractError("admitted_library_changed")

    def factors(self) -> list[dict[str, Any]]:
        library = FactorLibrary(self.library_path, read_only=True)
        try:
            return list(library.list_factors())
        finally:
            library.close()

    def factor(self, factor_id: str) -> dict[str, Any]:
        try:
            return next(r for r in self.factors() if r["factor_id"] == factor_id)
        except StopIteration:
            raise ContractError("unknown_factor_id") from None

    def factor_summary(self, factor_id: str, *, full: bool = False) -> dict[str, Any]:
        row = self.factor(factor_id)
        library = FactorLibrary(self.library_path, read_only=True)
        try:
            evaluations = library.evaluations(factor_id)
        finally:
            library.close()
        result = {
            k: row[k]
            for k in (
                "factor_id",
                "family",
                "mechanism",
                "hypothesis",
                "status",
                "origin",
                "provenance",
            )
        }
        result["evaluation_count"] = len(evaluations)
        result["development_metrics"] = [
            {
                "evaluation_id": e["evaluation_id"],
                "available_at": e["available_at"],
                "rank_ic": e.get("global", {}).get("decay_rank_ic", {}).get("60"),
                "similarity": e.get("global", {}).get("rank_similarity", {}),
            }
            for e in evaluations[-2:]
        ]
        if full:
            result["graph"] = row["graph"]
            result["lifecycle"] = row["lifecycle"][-8:]
        if "proposal_envelope" in row["provenance"]:
            result["proposal"] = json.loads(row["provenance"]["proposal_envelope"])
            result.update(evidence_semantics(FactorEvidenceMode.ADAPTIVE_RETROSPECTIVE))
        return {**result, **AUTHORITY}

    def market_summary(self) -> dict[str, Any]:
        model = self.admission.market_model.to_dict()
        return {
            "model_id": model["model_id"],
            "feature_config_id": identity(model["features"], "market-features"),
            "features": model["features"],
            "config": model["config"],
            "fit_window": model["fit_window"],
            "evaluation_scope": [f.to_dict()["evaluation"] for f in self.admission.folds],
            "state_definitions": model["state_interpretation"],
            "snapshot": self.admission.market_snapshot.to_dict(),
            "availability": "latest_admitted_historical_snapshot; not_live",
            **AUTHORITY,
        }

    def proposal_definition(
        self, proposal: FactorProposal, envelope: dict[str, Any]
    ) -> FactorRegistration:
        at = datetime.fromisoformat(envelope["proposed_at"])
        return FactorRegistration(
            proposal.graph,
            proposal.mechanism.value,
            proposal.mechanism.value,
            proposal.summary,
            FactorOrigin.AGENT,
            (
                ("agent_run_id", self.run_id),
                ("scope_id", self.admission.scope.scope_id),
                ("proposal_envelope", canonical_json(envelope)),
            ),
            at,
        )

    def register_proposal(self, proposal: FactorProposal, envelope: dict[str, Any]) -> str:
        definition = self.proposal_definition(proposal, envelope)
        library = FactorLibrary(self.library_path)
        try:
            return str(library.register(definition))
        finally:
            library.close()

    def development_admission(
        self, factors: tuple[FactorRegistration, ...], at: datetime
    ) -> AdaptiveDevelopmentAdmission:
        envelopes = {
            f.factor_id: json.loads(dict(f.provenance)["proposal_envelope"])
            for f in factors
            if f.origin is FactorOrigin.AGENT
        }
        admission = AdaptiveDevelopmentAdmission(
            at,
            self.run_id,
            self.admission.scope.scope_id,
            tuple(
                sorted(
                    (f.factor_id, str(_canonical_hash(f.to_dict(), prefix="factor-definition")))
                    for f in factors
                )
            ),
            canonical_json(envelopes),
        )
        admission.validate(factors, max(f.evaluation.end for f in self.admission.folds))
        return admission

    def evaluate_factor(self, factor_id: str, at: datetime, experiment_id: str) -> dict[str, Any]:
        try:
            return self._evaluate_factor(factor_id, at, experiment_id)
        except Exception:
            output = self.output / "experiments" / experiment_id
            if (output / "request.json").exists():
                write_immutable_json(
                    output / "failure.json",
                    {
                        "experiment_id": experiment_id,
                        "terminal": "FACTOR_EVALUATION_FAILED",
                        "reason": "trusted_factor_evaluator_failure",
                        **evidence_semantics(FactorEvidenceMode.ADAPTIVE_RETROSPECTIVE),
                    },
                )
            raise

    def _evaluate_factor(self, factor_id: str, at: datetime, experiment_id: str) -> dict[str, Any]:
        self.verify()
        factor = FactorRegistration.from_dict(self.factor(factor_id))
        fold = self.admission.folds[0]
        admission = self.development_admission((factor,), at)
        output = self.output / "experiments" / experiment_id
        write_immutable_json(
            output / "request.json",
            {
                "factor": factor.to_dict(),
                "host_id": identity(self.manifest, "r4-host"),
                "adaptive_development_selection": admission.to_dict(),
                **evidence_semantics(FactorEvidenceMode.ADAPTIVE_RETROSPECTIVE),
            },
        )
        report = evaluate_factor_library(
            (factor,),
            self.admission.source.read(fold.evaluation),
            self.admission.market_model,
            fold.evaluation,
            FactorEvaluationConfig(self.admission.economics),
            as_of=at,
        )[0]
        report.pop("evaluation_id")
        report.update(
            {
                "research_decision_at": utc_text(at),
                "available_at": utc_text(at),
                "adaptive_development_selection": admission.to_dict(),
                **evidence_semantics(FactorEvidenceMode.ADAPTIVE_RETROSPECTIVE),
            }
        )
        report["evaluation_id"] = _canonical_hash(report, prefix="factor-evaluation")
        library = FactorLibrary(self.library_path)
        try:
            library.transition(
                factor_id,
                FactorStatus.TESTING,
                at=at,
                actor="agent_controller",
                reason=f"run={self.run_id}; evaluated development proposal",
                evaluation_id=report["evaluation_id"],
            )
            library.record_evaluation(report)
        finally:
            library.close()
        write_immutable_json(output / "result.json", report)
        metrics = {"valid_count": sum(r["decay"]["60"] is not None for r in report["frames"])}
        if report["global"]["decay_rank_ic"]["60"] is not None:
            metrics["rank_ic"] = report["global"]["decay_rank_ic"]["60"]
        record = DevelopmentRecord(
            self.admission.scope.scope_id,
            self.admission.source.identity.identity,
            "evaluation",
            canonical_json(
                {
                    "candidate_id": factor_id,
                    "evaluator_id": self.admission.scope.evaluator_id,
                    "metrics": metrics,
                }
            ),
        )
        return {
            "outcome": "FACTOR_EVALUATED",
            "candidate_id": factor_id,
            "status": "TESTING",
            "evaluation_id": report["evaluation_id"],
            "record": record.to_dict(),
            "artifact_ref": f"experiments/{experiment_id}/result.json",
            **evidence_semantics(FactorEvidenceMode.ADAPTIVE_RETROSPECTIVE),
            **AUTHORITY,
        }

    def evaluate_portfolio(
        self, factor_ids: list[str], at: datetime, experiment_id: str
    ) -> dict[str, Any]:
        self.verify()
        factors = tuple(FactorRegistration.from_dict(self.factor(f)) for f in factor_ids)
        report = run_adaptive_portfolio(
            self.admission.source,
            factors,
            self.admission.folds,
            self.output / "experiments" / experiment_id,
            economics=self.admission.economics,
            feature_config=self.admission.market_model.features,
            gmm_config=self.admission.market_model.config,
            admission_mode=FactorEvidenceMode.ADAPTIVE_RETROSPECTIVE,
            adaptive_admission=self.development_admission(factors, at),
        )
        return {
            "summary": portfolio_feedback(report),
            "artifact_ref": f"experiments/{experiment_id}/result.json",
        }

    def transition(
        self, factor_id: str, status: str, at: datetime, reason: str, experiments: list[str]
    ) -> None:
        library = FactorLibrary(self.library_path)
        try:
            library.transition(
                factor_id,
                FactorStatus(status),
                at=at,
                actor="agent_controller",
                reason=canonical_json(
                    {"run_id": self.run_id, "reason": reason, "experiment_ids": experiments}
                ),
            )
        finally:
            library.close()
