from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from finagent.domain.research import TimeRange
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
from finagent.research.market_state import build_market_features
from finagent.research.market_state_gmm import fit_market_state
from finagent.research.us_a1_factor_graph import (
    FactorGraphSpec,
    FactorInputField,
    FactorNode,
    FactorOperator,
)
from finagent.research.us_a1_factor_materialization import compile_factor_graph_batch
from finagent.research.us_r3_economics import EconomicPolicy, simulate_session, summarize_sessions
from tests.test_market_state import market_fixture


def factors(at):
    return tuple(
        FactorRegistration(
            FactorGraphSpec(
                nodes=(
                    FactorNode("close", FactorOperator.INPUT, input_field=FactorInputField.CLOSE),
                    FactorNode("out", op, ("close",)),
                ),
                output_node_id="out",
            ),
            "synthetic_fixture",
            "ordered synthetic prices",
            "fixture diagnostic only",
            FactorOrigin.PROGRAMMATIC,
            (("test", "controlled_no_financial_claim"),),
            at,
        )
        for op in (FactorOperator.CROSS_SECTION_RANK, FactorOperator.CROSS_SECTION_ZSCORE)
    )


def evaluation_fixture():
    train, future, source, features, fit = market_fixture()
    # Deliberately ordered, constant percentage returns yield known RankIC=1.
    ordered = tuple(
        replace(
            a,
            bars=tuple(
                replace(
                    b,
                    open=100 * (1 + 0.001 * (j + 1)) ** i,
                    close=100 * (1 + 0.001 * (j + 1)) ** i,
                    high=101 * (1 + 0.001 * (j + 1)) ** i,
                    low=99 * (1 + 0.001 * (j + 1)) ** i,
                )
                for i, b in enumerate(a.bars)
            ),
        )
        for j, a in enumerate(future)
    )
    model = fit_market_state(build_market_features(train, source, features), fit)
    window = TimeRange(ordered[0].bars[0].event_time, ordered[0].bars[-1].available_at)
    definitions = factors(fit.start)
    config = FactorEvaluationConfig(EconomicPolicy(minimum_breadth=3, selection_count=1))
    return definitions, ordered, model, window, config


def test_real_graph_global_conditional_metrics_and_existing_economics():
    definitions, assets, model, window, config = evaluation_fixture()
    reports = evaluate_factor_library(
        definitions, (assets,), model, window, config, as_of=window.end
    )
    compiled = compile_factor_graph_batch(
        tuple(d.graph for d in definitions), admit_panel_operators=True
    )
    assert {r["factor_id"] for r in reports} == {r.candidate_id for r in compiled.roots}
    assert reports == evaluate_factor_library(
        definitions, (tuple(reversed(assets)),), model, window, config, as_of=window.end
    )
    for report in reports:
        expected_coverage = 1 if report["factor_id"] == definitions[0].factor_id else 25 / 26
        assert report["global"]["coverage"] == expected_coverage
        assert report["global"]["decay_rank_ic"]["15"] == pytest.approx(1.0)
        assert report["global"]["decay_rank_ic"]["60"] == pytest.approx(1.0)
        assert report["global"]["decay_observation_weight"] == {"15": 24, "60": 21}
        assert list(report["global"]["rank_similarity"].values()) == [pytest.approx(1)]
        assert len(report["by_market_state"]) == 4
        assert report["state_available_frames"] == 22
        assert report["state_unavailable_frames"] == 4
        assert sum(
            s["observation_weight"] for s in report["by_market_state"].values()
        ) == pytest.approx(22)
        for name, state in report["by_market_state"].items():
            index = int(name.split("_")[1])
            mass = sum(
                row["state_probabilities"][index]
                for row in report["frames"]
                if row["state_probabilities"]
            )
            assert state["observation_weight"] == pytest.approx(mass)
            assert state["coverage"] == 1 if mass else state["coverage"] is None
            assert set(state["economic_scenarios"]) == {"0.0", "1.0", "5.0", "10.0"}
        assert (
            report["alpha_authority"]
            is report["paper_authority"]
            is report["live_authority"]
            is False
        )
    # At the first bar all prices tie: percentile ranks are positive and the
    # existing selector chooses A0. Thereafter the highest price selects A3.
    prices = [{a.asset_id: a.bars[i].close for a in assets} for i in range(26)]
    targets = [{"A0": 1.0}] + [{"A3": 1.0}] * 25
    expected = summarize_sessions(
        [simulate_session(prices, targets, config.economics, cost_bps=5.0)]
    )
    assert reports[0]["global"]["economic_scenarios"]["5.0"] == expected


def test_registry_provenance_duplicate_lifecycle_and_persisted_queries(tmp_path):
    definitions, assets, model, window, config = evaluation_fixture()
    reports = evaluate_factor_library(
        definitions, (assets,), model, window, config, as_of=window.end
    )
    path = tmp_path / "library.sqlite"
    library = FactorLibrary(path)
    definition = definitions[0]
    identity = library.register(definition)
    assert library.register(definition) == identity
    assert len(library.list_factors()) == 1
    assert library.get(identity)["graph"] == definition.to_dict()["graph"]
    assert library.get(identity)["provenance"] == dict(definition.provenance)
    with pytest.raises(ValueError, match="duplicate factor"):
        library.register(replace(definition, hypothesis="changed interpretation"))
    with pytest.raises(ValueError, match="transition"):
        library.transition(
            identity, FactorStatus.ACTIVE, at=window.start, actor="test", reason="skip testing"
        )
    with pytest.raises(ValueError, match="TESTING"):
        library.record_evaluation(reports[0])
    library.transition(
        identity, FactorStatus.TESTING, at=window.start, actor="test", reason="evaluate"
    )
    library.transition(
        identity, FactorStatus.TESTING, at=window.start, actor="test", reason="evaluate"
    )
    assert len(library.get(identity)["lifecycle"]) == 2
    with pytest.raises(ValueError, match="available evaluation"):
        library.transition(
            identity, FactorStatus.ACTIVE, at=window.start, actor="test", reason="premature"
        )
    evidence = library.record_evaluation(reports[0])
    assert library.record_evaluation(reports[0]) == evidence
    assert library.evaluations(identity, as_of=window.end - timedelta(seconds=1)) == ()
    library.transition(
        identity,
        FactorStatus.ACTIVE,
        at=window.end,
        actor="test",
        reason="research member",
        evaluation_id=evidence,
    )
    library.close()
    library = FactorLibrary(path)
    try:
        assert library.get(identity)["status"] == FactorStatus.ACTIVE
        assert len(library.evaluations(identity)) == 1
        assert library.get(identity, as_of=window.start)["status"] == FactorStatus.TESTING
        library.transition(
            identity, FactorStatus.DORMANT, at=window.end, actor="test", reason="pause"
        )
        library.transition(
            identity, FactorStatus.RETIRED, at=window.end, actor="test", reason="retire"
        )
        with pytest.raises(ValueError, match="transition"):
            library.transition(
                identity, FactorStatus.TESTING, at=window.end, actor="test", reason="revive"
            )
        assert len(library.list_factors(status=FactorStatus.RETIRED)) == 1
        assert library.get(identity)["provenance"] == dict(definition.provenance)
        with pytest.raises(KeyError, match="unknown factor"):
            library.get("missing")
        with pytest.raises(KeyError, match="not available"):
            library.get(identity, as_of=definition.created_at - timedelta(seconds=1))
    finally:
        library.close()


def test_invalid_graph_and_duplicate_evaluation_inputs_rejected():
    definitions, assets, model, window, config = evaluation_fixture()
    with pytest.raises(ValueError, match="invalid FactorGraph"):
        replace(definitions[0], graph=replace(definitions[0].graph, output_node_id="missing"))
    with pytest.raises(ValueError, match="unique factors"):
        evaluate_factor_library(
            (definitions[0], definitions[0]), (assets,), model, window, config, as_of=window.end
        )
    with pytest.raises(ValueError, match="not available"):
        evaluate_factor_library(definitions, (assets,), model, window, config, as_of=window.start)
    with pytest.raises(ValueError, match="overlaps"):
        evaluate_factor_library(
            definitions,
            (assets,),
            model,
            TimeRange(model.fit_window.start, window.end),
            config,
            as_of=window.end,
        )


def test_missing_outcomes_do_not_rewrite_formation_coverage_and_invalidate_nav():
    definitions, assets, model, window, config = evaluation_fixture()
    first = evaluate_factor_library(
        definitions, (assets,), model, window, config, as_of=window.end
    )[0]
    changed = tuple(
        replace(a, bars=a.bars[:20] + tuple(replace(b, is_complete=False) for b in a.bars[20:]))
        for a in assets
    )
    second = evaluate_factor_library(
        definitions, (changed,), model, window, config, as_of=window.end
    )[0]
    assert [r["coverage"] for r in first["frames"][:20]] == [
        r["coverage"] for r in second["frames"][:20]
    ]
    assert second["frames"][19]["decay"]["15"] is None
    assert second["frames"][19]["coverage"] == 1
    assert second["global"]["economic_scenarios"]["5.0"]["compounded_return"] is None
    assert second["global"]["economic_scenarios"]["5.0"]["unresolved_sessions"] == 1
    assert second["frames"][-1]["decay"]["15"] is None
