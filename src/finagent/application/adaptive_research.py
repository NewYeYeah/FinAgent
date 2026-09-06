"""One inspectable OHLCV -> MarketState -> FactorLibrary development slice."""

from __future__ import annotations

from dataclasses import asdict
from importlib.metadata import version
from pathlib import Path
from platform import python_version
from typing import Any

from finagent.domain.research import TimeRange
from finagent.research.adaptive_inputs import DevelopmentPanelSource
from finagent.research.factor_library import FactorLibrary, FactorRegistration, FactorStatus
from finagent.research.factor_library_evaluation import (
    FactorEvaluationConfig,
    evaluate_factor_library,
    evaluation_implementation_id,
)
from finagent.research.market_state import (
    MarketFeatureConfig,
    MarketFeatures,
    build_market_features,
    utc_text,
)
from finagent.research.market_state_gmm import (
    GMMConfig,
    fit_market_state,
    market_state_implementation_id,
    project_market_state,
)
from finagent.research.us_baselines import _canonical_hash
from finagent.research.us_r3_economic_campaign import file_digest
from finagent.research.us_r3_usability import write_immutable_json


def run_adaptive_research_slice(
    source: DevelopmentPanelSource,
    factors: tuple[FactorRegistration, ...],
    fit_window: TimeRange,
    evaluation_window: TimeRange,
    output: Path,
    *,
    feature_config: MarketFeatureConfig | None = None,
    gmm_config: GMMConfig | None = None,
    evaluation_config: FactorEvaluationConfig,
) -> dict[str, Any]:
    """Freeze inputs before reading values. Persist negative/failed fit outcomes too.

    This executes a single declared train/project split. It performs no search,
    no factor selection and no independent confirmation or automatic activation.
    """
    feature_config = feature_config or MarketFeatureConfig()
    gmm_config = gmm_config or GMMConfig()
    if feature_config.proxy_asset not in source.universe:
        raise ValueError("declared market proxy is missing from the admitted universe")
    if fit_window.end > evaluation_window.start:
        raise ValueError("training and evaluation windows must not overlap")
    if any(f.created_at > evaluation_window.start for f in factors):
        raise ValueError("factor definitions must be frozen before evaluation")
    if len({f.factor_id for f in factors}) != len(factors) or not factors or len(factors) > 20:
        raise ValueError("a small unique factor library is required")
    request = {
        "version": "finagent.r4-research-slice.v1",
        "source": asdict(source.identity),
        "input_bindings": dict(source.bindings),
        "universe": source.universe,
        "factors": [f.to_dict() for f in factors],
        "fit_window": {"start": utc_text(fit_window.start), "end": utc_text(fit_window.end)},
        "evaluation_window": {
            "start": utc_text(evaluation_window.start),
            "end": utc_text(evaluation_window.end),
        },
        "features": feature_config.to_dict(),
        "gmm": asdict(gmm_config),
        "evaluation": asdict(evaluation_config),
        "scope": "local_development_only_no_search",
        "environment": {
            "python": python_version(),
            "packages": {
                name: version(name)
                for name in ("scikit-learn", "numpy", "scipy", "duckdb", "threadpoolctl")
            },
        },
        "implementation": {
            "application": file_digest(Path(__file__)),
            "input_adapter": file_digest(Path(__file__).parents[1] / "research/adaptive_inputs.py"),
            "market_state": market_state_implementation_id(),
            "factor_evaluation": evaluation_implementation_id(),
        },
    }
    request["run_id"] = _canonical_hash(request, prefix="r4-research-slice")
    write_immutable_json(output / "request.json", request)
    try:
        source.verify_unchanged()
        training = source.read(fit_window)
        train_features = MarketFeatures(
            source.identity,
            feature_config,
            tuple(
                row
                for session in training
                for row in build_market_features(session, source.identity, feature_config).rows
            ),
        )
        model = fit_market_state(train_features, fit_window, config=gmm_config)
        write_immutable_json(output / "market_state_model.json", model.to_dict())
        sessions = source.read(evaluation_window)
        state_rows = tuple(
            row
            for session in sessions
            for row in project_market_state(
                model,
                build_market_features(session, source.identity, feature_config),
                as_of=evaluation_window.end,
            )
        )
        reports = evaluate_factor_library(
            factors,
            sessions,
            model,
            evaluation_window,
            evaluation_config,
            as_of=evaluation_window.end,
        )
        source.verify_unchanged()
        library = FactorLibrary(output / "factor_library.sqlite")
        try:
            for factor, report in zip(factors, reports, strict=True):
                identity = library.register(factor)
                library.transition(
                    identity,
                    FactorStatus.TESTING,
                    at=evaluation_window.start,
                    actor="deterministic_core",
                    reason="declared development slice",
                )
                library.record_evaluation(report)
        finally:
            library.close()
        result = {
            "run_id": request["run_id"],
            "terminal": "DEVELOPMENT_SLICE_COMPLETE",
            "evaluation_data_status": "EVALUABLE"
            if any(r["global"]["coverage"] for r in reports)
            else "NO_EVALUABLE_FACTOR_OBSERVATIONS",
            "model_id": model.model_id,
            "states": [row.to_dict() for row in state_rows],
            "factor_evaluations": reports,
            "deterministic_comparator": "existing us_r2_regime_projection_v2; IWM lagged four-state; retained separately",
            "interpretation": "engineering development diagnostics; incremental market-state value not established",
            "alpha_authority": False,
            "paper_authority": False,
            "live_authority": False,
        }
        write_immutable_json(output / "result.json", result)
        return result
    except Exception as exc:
        write_immutable_json(
            output / "failure.json",
            {
                "run_id": request["run_id"],
                "terminal": "DEVELOPMENT_SLICE_FAILED",
                "reason": str(exc),
                "error_type": type(exc).__name__,
                "alpha_authority": False,
                "paper_authority": False,
                "live_authority": False,
            },
        )
        raise
