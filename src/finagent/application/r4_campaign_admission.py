"""Persist/reload R4ResearchAdmission, with train-only state fit and no PnL evaluation."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from typing import Any

from finagent.agents.r3_contracts import DevelopmentScope, canonical_json, identity
from finagent.application.research_controller_host import R4ResearchAdmission
from finagent.domain.research import TimeRange
from finagent.research.adaptive_inputs import DevelopmentPanelSource, bind_development_source
from finagent.research.adaptive_walkforward import WalkForwardFold
from finagent.research.factor_library import FactorLibrary, FactorOrigin, FactorRegistration
from finagent.research.market_state import (
    MarketFeatureConfig,
    MarketFeatures,
    MarketStateRow,
    build_market_features,
)
from finagent.research.market_state_gmm import (
    MarketStateModel,
    fit_market_state,
    project_market_state,
)
from finagent.research.us_r3_alpha_catalog import build_us_r3_executable_frontier_candidates
from finagent.research.us_r3_economic_campaign import file_digest
from finagent.research.us_r3_economics import EconomicPolicy
from finagent.research.us_r3_usability import write_immutable_json


def _source(config: dict[str, Any]) -> DevelopmentPanelSource:
    return bind_development_source(
        *(Path(config[k]) for k in ("source", "calendar", "base_plan", "evidence")),
        source_id=config["source_id"],
        source_revision=config["source_revision"],
        universe=tuple(config["universe"]),
    )


def prepare_research_admission(config: dict[str, Any], output: Path) -> R4ResearchAdmission:
    if output.exists() and any(output.iterdir()):
        raise ValueError("admission requires a fresh directory; never replace seed definitions")
    at = datetime.now(UTC)
    source = _source(config)
    sessions = [s for s in source.calendar.sessions if s.session_date.year == source.year]
    if not 240 <= len(sessions) <= 252:
        raise ValueError(
            "real v1 admission requires a complete annual calendar of 240..252 sessions"
        )
    # Calendar-only rule, not a function of factor quality or observed coverage.
    boundaries = [0, len(sessions) // 3, 2 * len(sessions) // 3, len(sessions)]
    folds = tuple(
        WalkForwardFold(
            f"fold-{i + 1}",
            TimeRange(sessions[start].open_at, sessions[start + 39].close_at),
            sessions[start + 19].close_at,
            TimeRange(sessions[start + 40].open_at, sessions[end - 1].close_at),
        )
        for i, (start, end) in enumerate(pairwise(boundaries))
    )
    write_immutable_json(
        output / "admission_request.json",
        {
            "config": config,
            "proposed_at": at.isoformat(),
            "folds": [f.to_dict() for f in folds],
            "input_bindings": dict(source.bindings),
            "source_read_scope": "TRAIN-prefix MarketState features only; no factor or portfolio outcomes",
        },
    )
    library_path = output / "seed_factor_library.sqlite"
    library = FactorLibrary(library_path)
    try:
        for candidate in build_us_r3_executable_frontier_candidates():
            library.register(
                FactorRegistration(
                    candidate.graph,
                    candidate.strategy.slug,
                    candidate.strategy.mechanism,
                    candidate.hypothesis.summary,
                    FactorOrigin.MANUAL,
                    (
                        ("origin", "existing_R3_executable_frontier"),
                        ("historically_predeclared", "false"),
                        ("research_semantics", "frozen_now_before_retrospective_campaign"),
                    ),
                    at,
                )
            )
    finally:
        library.close()
    first = folds[0]
    prefix = TimeRange(first.train.start, first.state_fit_end)
    features = MarketFeatureConfig(config["proxy_asset"])
    rows = tuple(
        row
        for s in source.read(prefix)
        for row in build_market_features(s, source.identity, features).rows
    )
    model = fit_market_state(MarketFeatures(source.identity, features, rows), prefix)
    # First calibration session is after the train-prefix model became available.
    calibration = source.read(TimeRange(sessions[20].open_at, sessions[20].close_at))[0]
    snapshot = project_market_state(
        model,
        build_market_features(calibration, source.identity, features),
        as_of=sessions[20].close_at,
    )[-1]
    admission = R4ResearchAdmission(
        source,
        folds,
        library_path,
        EconomicPolicy(),
        model,
        snapshot,
        DevelopmentScope(
            "r4-real-development-2025",
            (),
            source.identity.identity,
            "r4-factor-library-and-adaptive-portfolio-v1",
        ),
        at,
    )
    write_immutable_json(
        output / "research_admission.json",
        {
            "config": config,
            "manifest": admission.manifest(),
            "seed_library_name": library_path.name,
            "seed_library_digest": file_digest(library_path),
            "scope_name": admission.scope.scope_id,
        },
    )
    return admission


def load_research_admission(output: Path) -> R4ResearchAdmission:
    bundle = json.loads((output / "research_admission.json").read_text())
    row = bundle["manifest"]
    source = _source(bundle["config"])
    library = output / bundle["seed_library_name"]
    if file_digest(library) != bundle["seed_library_digest"]:
        raise ValueError("seed library drift")
    snapshot = row["market_snapshot"]
    economics = row["economics"]
    admission = R4ResearchAdmission(
        source,
        tuple(WalkForwardFold.from_dict(f) for f in row["folds"]),
        library,
        EconomicPolicy(**{**economics, "cost_bps": tuple(economics["cost_bps"])}),
        MarketStateModel.from_dict(row["market_model"]),
        MarketStateRow(
            snapshot["model_id"],
            datetime.fromisoformat(snapshot["event_time"]),
            datetime.fromisoformat(snapshot["available_at"]),
            snapshot["session_id"],
            tuple(snapshot["probabilities"]) if snapshot["probabilities"] else None,
            snapshot["unavailable_reason"],
        ),
        DevelopmentScope(
            bundle["scope_name"], (), row["evaluation_source_id"], row["evaluator_id"]
        ),
        datetime.fromisoformat(row["admitted_at"]),
    )
    if identity(json.loads(canonical_json(admission.manifest())), "admission") != identity(
        row, "admission"
    ):
        raise ValueError("research admission changed; new version required")
    return admission
