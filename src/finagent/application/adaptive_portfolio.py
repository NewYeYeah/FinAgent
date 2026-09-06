"""Freeze and persist the deterministic R4 walk-forward comparison."""

from __future__ import annotations

from dataclasses import asdict
from importlib.metadata import version
from pathlib import Path
from platform import python_version
from typing import Any

from finagent.research.adaptive_factor_admission import (
    AdaptiveDevelopmentAdmission,
    FactorEvidenceMode,
    evidence_semantics,
)
from finagent.research.adaptive_inputs import DevelopmentPanelSource
from finagent.research.adaptive_walkforward import (
    WalkForwardFold,
    evaluate_walkforward_fold,
    summarize_folds,
    validate_walkforward,
    validate_walkforward_layout,
)
from finagent.research.factor_library import FactorLibrary, FactorRegistration, FactorStatus
from finagent.research.factor_performance import NORMALIZATION, SUPPORT_RULE, QualityConfig
from finagent.research.market_state import MarketFeatureConfig, utc_text
from finagent.research.market_state_gmm import GMMConfig
from finagent.research.ridge_meta_allocator import RidgeConfig
from finagent.research.us_baselines import _canonical_hash
from finagent.research.us_r3_economic_campaign import file_digest
from finagent.research.us_r3_economics import EconomicPolicy
from finagent.research.us_r3_usability import write_immutable_json


def allocation_implementation_ids() -> dict[str, str]:
    root = Path(__file__).parents[1]
    names = (
        "application/adaptive_portfolio.py",
        "research/adaptive_walkforward.py",
        "research/adaptive_portfolio_evaluation.py",
        "research/factor_performance.py",
        "research/factor_allocators.py",
        "research/ridge_meta_allocator.py",
        "research/market_state.py",
        "research/market_state_gmm.py",
        "research/adaptive_inputs.py",
        "research/factor_library.py",
        "research/factor_library_evaluation.py",
        "research/us_a1_factor_graph.py",
        "research/us_a1_factor_validation.py",
        "research/us_a1_factor_materialization.py",
        "research/us_a1_factor_panel_materialization.py",
        "research/us_baseline_evaluation.py",
        "research/us_r3_economics.py",
        "research/us_r3_economic_campaign.py",
        "research/us_r3_usability.py",
        "domain/trading.py",
        "domain/research.py",
        "domain/trading_calendar.py",
    )
    return {name: file_digest(root / name) for name in names}


def load_factor_pool(
    path: Path, factor_ids: tuple[str, ...] = ()
) -> tuple[tuple[FactorRegistration, ...], tuple[str, str]]:
    """Read definitions/lifecycle only. Window-end aggregate metrics are never read."""
    binding = (str(path.resolve()), file_digest(path))
    library = FactorLibrary(path, read_only=True)
    try:
        rows = (
            [library.get(factor) for factor in factor_ids]
            if factor_ids
            else list(library.list_factors())
        )
        if not rows or any(
            row["status"] in (FactorStatus.REJECTED, FactorStatus.RETIRED) for row in rows
        ):
            raise ValueError("explicit pool must contain existing nonterminal research factors")
        factors = tuple(
            sorted((FactorRegistration.from_dict(row) for row in rows), key=lambda f: f.factor_id)
        )
    finally:
        library.close()
    if file_digest(path) != binding[1]:
        raise ValueError("FactorLibrary changed during definition read")
    return factors, binding


def run_adaptive_portfolio(
    source: DevelopmentPanelSource,
    factors: tuple[FactorRegistration, ...],
    folds: tuple[WalkForwardFold, ...],
    output: Path,
    *,
    economics: EconomicPolicy,
    feature_config: MarketFeatureConfig | None = None,
    gmm_config: GMMConfig | None = None,
    quality_config: QualityConfig | None = None,
    ridge_config: RidgeConfig | None = None,
    library_binding: tuple[str, str] | None = None,
    admission_mode: FactorEvidenceMode = FactorEvidenceMode.PREDECLARED_STATIC,
    adaptive_admission: AdaptiveDevelopmentAdmission | None = None,
) -> dict[str, Any]:
    features, gmm = feature_config or MarketFeatureConfig(), gmm_config or GMMConfig()
    quality, ridge = quality_config or QualityConfig(), ridge_config or RidgeConfig()
    if admission_mode is FactorEvidenceMode.PREDECLARED_STATIC:
        if adaptive_admission is not None:
            raise ValueError("static admission cannot carry an adaptive proposal envelope")
        validate_walkforward(factors, folds, economics)
    elif (
        admission_mode is FactorEvidenceMode.ADAPTIVE_RETROSPECTIVE
        and adaptive_admission is not None
    ):
        validate_walkforward_layout(factors, folds, economics)
        adaptive_admission.validate(factors, max(f.evaluation.end for f in folds))
    else:
        raise ValueError("explicit retrospective admission requires a frozen proposal envelope")
    research_decision_at = (
        adaptive_admission.requested_at if adaptive_admission is not None else None
    )
    if features.proxy_asset not in source.universe:
        raise ValueError("market proxy must be in the explicit universe")
    request = {
        "version": "finagent.deterministic-adaptive-request.v1",
        "source": asdict(source.identity),
        "input_bindings": dict(source.bindings),
        "input_library_binding": library_binding,
        "universe": source.universe,
        "factors": [f.to_dict() for f in sorted(factors, key=lambda f: f.factor_id)],
        "folds": [f.to_dict() for f in folds],
        "normalization": NORMALIZATION,
        "support_rule": SUPPORT_RULE,
        "gmm": asdict(gmm),
        "features": features.to_dict(),
        "quality": asdict(quality),
        "ridge": asdict(ridge),
        "economics": asdict(economics),
        "schedule": "rolling_sleeves",
        "arms": [
            "equal_weight",
            "rolling_ic",
            "rolling_net_return",
            "regime_conditional",
            "ridge_meta",
        ],
        "environment": {
            "python": python_version(),
            "packages": {
                name: version(name)
                for name in ("scikit-learn", "numpy", "scipy", "duckdb", "threadpoolctl")
            },
        },
        "implementation": allocation_implementation_ids(),
        "scope": "local_development_only_no_search_no_exposure_timing",
    }
    if research_decision_at is not None:
        assert adaptive_admission is not None
        request["adaptive_development_selection"] = adaptive_admission.to_dict()
        request.update(evidence_semantics(FactorEvidenceMode.ADAPTIVE_RETROSPECTIVE))
    request["run_id"] = _canonical_hash(request, prefix="adaptive-walkforward-run")
    write_immutable_json(output / "request.json", request)
    completed: list[dict[str, Any]] = []
    library = None
    try:
        source.verify_unchanged()
        if library_binding and file_digest(Path(library_binding[0])) != library_binding[1]:
            raise ValueError("bound input FactorLibrary changed")
        library = FactorLibrary(output / "factor_library.sqlite")
        for factor in factors:
            library.register(factor)
            library.transition(
                factor.factor_id,
                FactorStatus.TESTING,
                at=research_decision_at or folds[0].train.start,
                actor="deterministic_core",
                reason="frozen walk-forward factor pool",
            )
        for fold in folds:
            report = evaluate_walkforward_fold(
                source, factors, fold, features, gmm, quality, ridge, economics
            )
            completed.append(report)
            # Research registry reuses its existing evaluation table. The release
            # stream lives in immutable JSON; no allocator database is created.
            for factor in factors:
                observations = [
                    r
                    for r in report["performance_history"]
                    if r["factor_id"] == factor.factor_id
                    and r["decision_time"] >= report["fold"]["evaluation"]["start"]
                ]
                evidence = {
                    "version": "finagent.factor-session-performance.v1",
                    "factor_id": factor.factor_id,
                    "model_id": report["state_model"]["model_id"],
                    "window": report["fold"]["evaluation"],
                    "available_at": report["fold"]["evaluation"]["end"],
                    "observations": observations,
                    "scope": "completed_session_performance_under_common_support_and_fixed_exposure",
                    "normalization": NORMALIZATION,
                    "support_rule": SUPPORT_RULE,
                    "economic_policy": asdict(economics),
                    "implementation_id": _canonical_hash(
                        request["implementation"], prefix="allocator-implementation"
                    ),
                    "alpha_authority": False,
                    "paper_authority": False,
                    "live_authority": False,
                }
                if research_decision_at is not None:
                    evidence["adaptive_development_selection"] = request[
                        "adaptive_development_selection"
                    ]
                    evidence.update(evidence_semantics(FactorEvidenceMode.ADAPTIVE_RETROSPECTIVE))
                    evidence["research_decision_at"] = utc_text(research_decision_at)
                    evidence["available_at"] = utc_text(research_decision_at)
                evidence["evaluation_id"] = _canonical_hash(evidence, prefix="factor-evaluation")
                library.record_evaluation(evidence)
        source.verify_unchanged()
        if library_binding and file_digest(Path(library_binding[0])) != library_binding[1]:
            raise ValueError("bound input FactorLibrary changed")
        result = {
            "version": "finagent.deterministic-adaptive-result.v1",
            "run_id": request["run_id"],
            "terminal": "DETERMINISTIC_WALKFORWARD_COMPLETE",
            "folds": completed,
            "overall": summarize_folds(completed),
            "interpretation": "controlled_development_evidence; GMM_incremental_value_and_allocator_profitability_not_established",
            "alpha_authority": False,
            "paper_authority": False,
            "live_authority": False,
        }
        if research_decision_at is not None:
            result["adaptive_development_selection"] = request["adaptive_development_selection"]
            result.update(evidence_semantics(FactorEvidenceMode.ADAPTIVE_RETROSPECTIVE))
        write_immutable_json(output / "result.json", result)
        return result
    except Exception as exc:
        write_immutable_json(
            output / "failure.json",
            {
                "run_id": request["run_id"],
                "terminal": "DETERMINISTIC_WALKFORWARD_FAILED",
                "reason": str(exc),
                "error_type": type(exc).__name__,
                "completed_folds": completed,
                **(
                    {
                        "adaptive_development_selection": request["adaptive_development_selection"],
                        **evidence_semantics(FactorEvidenceMode.ADAPTIVE_RETROSPECTIVE),
                    }
                    if research_decision_at is not None
                    else {}
                ),
                "alpha_authority": False,
                "paper_authority": False,
                "live_authority": False,
            },
        )
        raise
    finally:
        if library is not None:
            library.close()
