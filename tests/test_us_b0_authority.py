from __future__ import annotations

import pytest

from finagent.research.us_baseline_authority import bind_current_us_b0_run_spec
from finagent.research.us_baselines import canonical_us_baseline_denominator


def _documents() -> tuple[dict[str, object], dict[str, object], tuple[str, ...]]:
    assets = tuple(f"T{index:02d}" for index in range(20))
    universe_id = "engineering-universe-test"
    universe: dict[str, object] = {
        "schema_version": "finagent.us-engineering-universe-finalization-report.v3",
        "accepted": True,
        "blockers": [],
        "universe_id": universe_id,
        "accepted_mapping_count": len(assets),
        "selected_symbols": list(assets),
        "quote_evidence": {
            "passed": True,
            "clock_evidence_passed": True,
            "quote_probe_policy_matches": True,
        },
        "materialization": {
            "mappings": [
                {
                    "status": "accepted_for_engineering",
                    "research": {"source_symbol": asset},
                }
                for asset in assets
            ]
        },
    }
    certification: dict[str, object] = {
        "schema_version": "finagent.us-minute-certification-report.v1",
        "report_id": "us-minute-research-cert-test",
        "certified": True,
        "outcome": "CERTIFIED_FOR_ENGINEERING_RESEARCH",
        "blockers": [],
        "inputs": {
            "engineering_universe_id": universe_id,
            "engineering_universe_accepted": True,
            "engineering_universe_count": len(assets),
            "reconciliation_passed": True,
        },
    }
    return certification, universe, assets


def test_current_binder_accepts_v3_only_with_clock_hardening_evidence() -> None:
    certification, universe, assets = _documents()
    denominator = canonical_us_baseline_denominator()

    run_spec, selected = bind_current_us_b0_run_spec(
        certification,
        universe,
        denominator=denominator,
    )

    assert selected == assets
    assert run_spec.engineering_universe_id == universe["universe_id"]

    quote_evidence = dict(universe["quote_evidence"])  # type: ignore[arg-type]
    quote_evidence["clock_evidence_passed"] = False
    bad = dict(universe)
    bad["quote_evidence"] = quote_evidence
    with pytest.raises(ValueError, match="broker-clock"):
        bind_current_us_b0_run_spec(certification, bad, denominator=denominator)


def test_current_binder_rejects_unknown_future_schema() -> None:
    certification, universe, _assets = _documents()
    universe["schema_version"] = "finagent.us-engineering-universe-finalization-report.v99"

    with pytest.raises(ValueError, match="v2 or v3"):
        bind_current_us_b0_run_spec(
            certification,
            universe,
            denominator=canonical_us_baseline_denominator(),
        )
