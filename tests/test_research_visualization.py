from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from finagent.visualization.feature_store import load_feature_store
from finagent.visualization.research_report import ResearchReportError, parse_research_report
from finagent.visualization.trace_reader import parse_agent_trace


DIGEST_A = "a" * 64
DIGEST_B = "b" * 64


def _candidate(feature_id: str, digest: str, rank_icir: float, sharpe: float):
    horizons = {}
    for label, divisor in (
        ("forward_simple_return_1", 10.0),
        ("forward_simple_return_5", 12.0),
    ):
        horizons[label] = {
            "label_name": label,
            "pearson_ic": rank_icir / divisor,
            "pearson_icir": rank_icir,
            "rank_ic": rank_icir / divisor,
            "rank_icir": rank_icir,
            "periods": 300,
        }
    return {
        "feature_id": feature_id,
        "feature_digest": digest,
        "primary_label": "forward_simple_return_1",
        "horizon_diagnostics": horizons,
        "quantile_diagnostics": {
            "quantile_mean_returns": [-0.002, -0.001, 0.0, 0.001, 0.002],
            "long_short_mean_return": 0.004,
            "long_short_sharpe": sharpe,
            "mean_one_way_turnover": 0.25,
            "periods": 300,
        },
        "coverage": 0.98,
    }


def _stability(feature_id: str, digest: str, pvalue: float):
    return {
        "feature_id": feature_id,
        "feature_digest": digest,
        "primary_label": "forward_simple_return_1",
        "periods": 300,
        "dominant_direction": 1,
        "positive_rank_ic_ratio": 0.62,
        "sign_consistency_ratio": 0.62,
        "hac": {"lags": 5, "tstat": 2.2, "pvalue": pvalue},
        "block_bootstrap": {
            "pvalue": min(1.0, pvalue + 0.01),
            "ci_lower": 0.001,
            "ci_upper": 0.02,
        },
        "quantile_monotonicity": 0.9,
        "turnover_std": 0.05,
        "coverage_mean": 0.98,
        "coverage_min": 0.9,
        "horizon_sign_consistency": 1.0,
        "horizon_rank_ic": {
            "forward_simple_return_1": 0.02,
            "forward_simple_return_5": 0.01,
        },
        "rolling_rank_ic": [
            {
                "start": "2022-01-01T00:00:00+00:00",
                "end": "2022-04-01T00:00:00+00:00",
                "rank_ic": 0.02,
                "rank_icir": 0.1,
                "periods": 63,
            }
        ],
        "subperiods": [
            {
                "period": "2022",
                "start": "2022-01-01T00:00:00+00:00",
                "end": "2022-12-31T00:00:00+00:00",
                "rank_ic": 0.02,
                "rank_icir": 0.1,
                "periods": 250,
            }
        ],
    }


def _multiplicity(digest: str, pvalue: float):
    return {
        "feature_digest": digest,
        "raw_hac_pvalue": pvalue,
        "holm_adjusted_pvalue": min(1.0, pvalue * 2),
        "bh_qvalue": min(1.0, pvalue * 2),
    }


def _report():
    development = [
        _candidate("factor-a", DIGEST_A, 0.15, 0.7),
        _candidate("factor-b", DIGEST_B, 0.10, 0.4),
    ]
    validation = [
        _candidate("factor-a", DIGEST_A, -0.02, -0.3),
        _candidate("factor-b", DIGEST_B, 0.18, 0.5),
    ]
    universe_split = {
        "timestamps": 700,
        "assets": 150,
        "warmup_timestamps": 60,
        "first_session_eligible_assets": 141,
        "eligible_cells": 98000,
        "average_eligible_assets": 140.0,
        "minimum_eligible_assets": 132,
        "maximum_eligible_assets": 146,
        "rejected_counts": {"liquidity": 900},
    }
    return {
        "schema_version": "finagent.ashare-factor-research-acceptance.v2",
        "acceptance_id": "acceptance-test",
        "mode": "agent",
        "passed": True,
        "system_acceptance": {"passed": True, "status": "PASS"},
        "research_outcome": {
            "status": "ENSEMBLE_VALIDATION_FAILED",
            "ensemble_validation_passed": False,
            "promotion_eligible": False,
            "reason_codes": ["TEST"],
            "policy": {},
        },
        "data_version": "data-v1",
        "candidate_universe": {
            "selection_id": "selection-v1",
            "selection_date": "2017-12-29",
            "size": 150,
            "scope": "candidate-only",
        },
        "universe_policy": {
            "report_id": "universe-v1",
            "data_version": "universe-data-v1",
            "splits": {
                "development": dict(universe_split),
                "validation": dict(universe_split),
            },
        },
        "candidate_denominator": [
            {
                "feature_id": "factor-a",
                "feature_digest": DIGEST_A,
                "hypothesis": "A",
                "input_fields": ["simple_return_5"],
                "lookback": 1,
                "generator_id": "deepseek:test",
            },
            {
                "feature_id": "factor-b",
                "feature_digest": DIGEST_B,
                "hypothesis": "B",
                "input_fields": ["turnover_rate"],
                "lookback": 20,
                "generator_id": "deepseek:test",
            },
        ],
        "development_report": {
            "report_id": "dev-v1",
            "candidates": development,
            "factor_value_correlations": {f"{DIGEST_A}|{DIGEST_B}": 0.2},
        },
        "validation_report": {
            "report_id": "val-v1",
            "candidates": validation,
            "factor_value_correlations": {f"{DIGEST_A}|{DIGEST_B}": 0.3},
        },
        "frozen_ensemble": {
            "ensemble_id": "ensemble-v1",
            "components": [
                {
                    "feature_id": "factor-a",
                    "feature_digest": DIGEST_A,
                    "weight": 1.0,
                    "direction": 1,
                }
            ],
        },
        "validation_ensemble": _candidate("ensemble", "ensemble-v1", -0.04, -0.8),
        "validation_comparison": {
            "ensemble_minus_best_single_rank_icir": -0.22,
            "ensemble_minus_best_single_long_short_sharpe": -1.3,
        },
        "development_stability": {
            "report_id": "dev-stability-v1",
            "candidates": [
                _stability("factor-a", DIGEST_A, 0.04),
                _stability("factor-b", DIGEST_B, 0.04),
            ],
            "multiplicity": {
                DIGEST_A: _multiplicity(DIGEST_A, 0.04),
                DIGEST_B: _multiplicity(DIGEST_B, 0.04),
            },
        },
        "validation_stability": {
            "report_id": "val-stability-v1",
            "candidates": [
                _stability("factor-a", DIGEST_A, 0.8),
                _stability("factor-b", DIGEST_B, 0.02),
            ],
            "multiplicity": {
                DIGEST_A: _multiplicity(DIGEST_A, 0.8),
                DIGEST_B: _multiplicity(DIGEST_B, 0.02),
            },
        },
        "validation_ensemble_stability": _stability(
            "ensemble", "ensemble-v1", 0.9
        ),
        "reserve": {
            "start": "2025-01-01",
            "end": "2026-08-22",
            "status": "untouched",
        },
        "discovery": {
            "discovery_id": "discovery-v1",
            "rounds": [
                {
                    "round_index": 1,
                    "new_candidate_digests": [DIGEST_A],
                    "cumulative_candidate_digests": [DIGEST_A],
                    "cumulative_report_id": "round-1",
                    "selection": {"components": [{"feature_digest": DIGEST_A}]},
                    "feedback_id": "feedback-1",
                },
                {
                    "round_index": 2,
                    "new_candidate_digests": [DIGEST_B],
                    "cumulative_candidate_digests": [DIGEST_A, DIGEST_B],
                    "cumulative_report_id": "round-2",
                    "selection": {"components": [{"feature_digest": DIGEST_B}]},
                    "feedback_id": "feedback-2",
                },
            ],
        },
    }


def test_report_view_aligns_denominator_and_builds_views() -> None:
    view = parse_research_report(json.dumps(_report()))
    assert view.system_passed is True
    assert view.research_status == "ENSEMBLE_VALIDATION_FAILED"
    assert view.has_stability is True
    rows = view.candidate_rows()
    assert len(rows) == 2
    assert rows[0]["selected"] is True
    assert rows[1]["validation_rank_icir"] == pytest.approx(0.18)
    assert view.rolling_rows(DIGEST_B, "validation")[0]["rank_ic"] == pytest.approx(0.02)
    labels, matrix = view.correlation_matrix("validation")
    assert labels == ["factor-a", "factor-b"]
    assert matrix[0][1] == pytest.approx(0.3)
    assert view.discovery_rounds()[1]["feedback_id"] == "feedback-2"
    assert view.universe_rows()[1]["first_session_eligible_assets"] == 141


def test_report_view_rejects_denominator_drift() -> None:
    payload = _report()
    payload["validation_report"]["candidates"].pop()
    with pytest.raises(ResearchReportError, match="validation report denominator"):
        parse_research_report(json.dumps(payload))


def test_trace_reader_merges_attributes_and_reports_usage() -> None:
    trace = "\n".join(
        json.dumps(value)
        for value in (
            {
                "event": "span_start",
                "span_id": "root",
                "parent_span_id": None,
                "name": "discovery",
                "kind": "AGENT",
                "at": "2026-01-01T00:00:00+00:00",
                "attributes": {},
            },
            {
                "event": "span_start",
                "span_id": "llm",
                "parent_span_id": "root",
                "name": "completion",
                "kind": "LLM",
                "at": "2026-01-01T00:00:01+00:00",
                "attributes": {"llm.model_name": "deepseek-v4-pro"},
            },
            {
                "event": "event",
                "span_id": "llm",
                "name": "attributes",
                "at": "2026-01-01T00:00:02+00:00",
                "attributes": {
                    "llm.token_count.prompt": 100,
                    "llm.token_count.completion": 10000,
                    "llm.token_count.total": 10100,
                    "finagent.reasoning_tokens": 9000,
                    "finagent.latency_ms": 2500,
                },
            },
            {
                "event": "span_end",
                "span_id": "llm",
                "status": "ok",
                "at": "2026-01-01T00:00:04+00:00",
            },
            {
                "event": "span_end",
                "span_id": "root",
                "status": "ok",
                "at": "2026-01-01T00:00:05+00:00",
            },
        )
    )
    view = parse_agent_trace(trace)
    assert view.depth(view.span("llm")) == 1
    assert view.total_tokens == 10100
    assert view.total_reasoning_tokens == 9000
    assert view.llm_rows()[0]["latency_ms"] == pytest.approx(2500)


def test_feature_store_is_opened_read_only(tmp_path: Path) -> None:
    database = tmp_path / "generated_features.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE generated_features (digest TEXT PRIMARY KEY, feature_id TEXT, "
            "source TEXT, payload_json TEXT, generated_at TEXT)"
        )
        payload = {
            "spec": {"feature_id": "factor-a"},
            "validation": {"validator_version": "v1"},
            "generator_id": "deepseek:test",
            "smoke_output_digest": "smoke",
            "metadata": {"task_id": "task"},
        }
        connection.execute(
            "INSERT INTO generated_features VALUES (?, ?, ?, ?, ?)",
            (
                DIGEST_A,
                "factor-a",
                "def compute_feature(inputs):\n    return inputs['x']\n",
                json.dumps(payload),
                "2026-01-01T00:00:00+00:00",
            ),
        )
    before = database.stat().st_mtime_ns
    features = load_feature_store(database, digests=(DIGEST_A,))
    after = database.stat().st_mtime_ns
    assert features[DIGEST_A].feature_id == "factor-a"
    assert before == after


def test_plotly_figure_builders() -> None:
    pytest.importorskip("plotly")
    from finagent.visualization.figures import (
        correlation_heatmap,
        development_validation_scatter,
        ensemble_weights,
        quantile_returns,
        rolling_rank_ic,
        subperiod_rank_ic,
        universe_eligibility,
    )

    view = parse_research_report(json.dumps(_report()))
    figures = (
        development_validation_scatter(view),
        rolling_rank_ic(view, DIGEST_A),
        subperiod_rank_ic(view, DIGEST_A),
        quantile_returns(view, DIGEST_A),
        correlation_heatmap(view, "development"),
        ensemble_weights(view),
        universe_eligibility(view),
    )
    assert all(figure.data for figure in figures)
