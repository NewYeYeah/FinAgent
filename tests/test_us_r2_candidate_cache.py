from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

from finagent.research.us_agent_value_gate import USAgentValueGateDecision
from finagent.research.us_agent_value_protocol import (
    USAgentValueArm,
    USAgentValuePhase,
    canonical_us_a0_primitive_vocabulary,
)
from finagent.research.us_baselines import (
    USBaselineBar,
    USBaselineProtocol,
    USBaselineUnavailableReason,
    evaluate_us_baseline_feature,
)
from finagent.research.us_r1_protocol import (
    USR1AgentScope,
    USR1CandidateDenominator,
    USR1CandidateProvenance,
    canonical_us_r1_research_protocol,
)
from finagent.research.us_r2_base_panel_batch import (
    USR2BasePanelBatchEvidence,
    USR2CompletedAnnualBasePanel,
    canonical_us_r2_base_panel_years,
)
from finagent.research.us_r2_candidate_cache import (
    FROZEN_CANDIDATE_COUNT,
    combine_us_r2_asset_candidate_caches,
    compile_us_r2_candidate_execution,
    load_us_r2_candidate_npz,
    materialize_us_r2_asset_candidate_cache,
    validate_us_r2_base_panel_batch_gate,
    validate_us_r2_candidate_denominator,
    write_deterministic_us_r2_candidate_npz,
)


def _denominator() -> USR1CandidateDenominator:
    candidates = canonical_us_a0_primitive_vocabulary().all_candidates()[:FROZEN_CANDIDATE_COUNT]
    provenance = tuple(
        USR1CandidateProvenance(
            candidate=candidate,
            source_arms=(USAgentValueArm.MANUAL,),
            source_run_ids=(f"synthetic-run-{index:02d}",),
        )
        for index, candidate in enumerate(candidates)
    )
    return USR1CandidateDenominator(
        protocol_id=canonical_us_r1_research_protocol().protocol_id,
        a0_phase=USAgentValuePhase.FORMAL,
        a0_experiment_id="synthetic-a0-experiment",
        a0_gate_review_id="synthetic-a0-review",
        a0_gate_decision=USAgentValueGateDecision.FORMAL_NO_INCREMENTAL_VALUE,
        agent_scope=USR1AgentScope.CONTRACTED,
        candidates=provenance,
    )


def _bars() -> tuple[USBaselineBar, ...]:
    starts = (
        datetime(2020, 1, 2, 14, 30, tzinfo=UTC),
        datetime(2020, 1, 3, 14, 30, tzinfo=UTC),
        datetime(2020, 1, 6, 14, 30, tzinfo=UTC),
    )
    rows: list[USBaselineBar] = []
    global_index = 0
    for session_number, start in enumerate(starts):
        session_id = start.date().isoformat()
        for bar_index in range(26):
            event_time = start + timedelta(minutes=15 * bar_index)
            base = 100.0 + session_number * 4.0 + bar_index * 0.21
            close = base + ((bar_index % 5) - 2) * 0.03
            if session_number == 1 and bar_index == 5:
                open_value = close
                high = close
                low = close
            else:
                open_value = base - 0.02
                high = max(open_value, close) + 0.16
                low = min(open_value, close) - 0.14
            volume = 0.0 if session_number == 2 and bar_index < 12 else 1_000.0 + global_index
            is_complete = not (session_number == 1 and bar_index == 12)
            rows.append(
                USBaselineBar(
                    event_time=event_time,
                    available_at=event_time + timedelta(minutes=15),
                    session_id=session_id,
                    open=open_value,
                    high=high,
                    low=low,
                    close=close,
                    volume=volume,
                    is_complete=is_complete,
                )
            )
            global_index += 1
    return tuple(rows)


def _rows() -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = []
    for index, bar in enumerate(_bars()):
        bar_index = index % 26
        label_available = bar_index < 22
        rows.append(
            {
                "research_asset_id": "AAPL",
                "session_date": bar.event_time.date(),
                "session_id": bar.session_id,
                "event_time": bar.event_time,
                "available_at": bar.available_at,
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume,
                "is_complete": bar.is_complete,
                "source_available_at": bar.available_at,
                "source_price": bar.close,
                "target_available_at": (
                    bar.available_at + timedelta(minutes=60) if label_available else None
                ),
                "label_value": 0.01 + index * 1e-6 if label_available else None,
                "label_available": label_available,
                "unavailable_reason": None if label_available else "target_crosses_session",
                "label_row_present": True,
            }
        )
    return tuple(rows)


def test_37_candidate_mapping_preserves_r1_bitwise_semantics() -> None:
    denominator = _denominator()
    execution = compile_us_r2_candidate_execution(denominator)
    rows = _rows()
    bars = _bars()
    cache = materialize_us_r2_asset_candidate_cache(
        rows,
        execution,
        expected_asset="AAPL",
    )

    assert len(execution.bindings) == FROZEN_CANDIDATE_COUNT
    assert execution.compiled.unique_node_count < execution.compiled.naive_node_count
    assert tuple(item.r1_candidate_id for item in execution.bindings) == tuple(
        item.candidate.candidate_id for item in denominator.candidates
    )

    expected_reason_codes = {
        USBaselineUnavailableReason.INSUFFICIENT_HISTORY: 1,
        USBaselineUnavailableReason.CROSS_SESSION_WINDOW: 2,
        USBaselineUnavailableReason.INCOMPLETE_BAR: 3,
        USBaselineUnavailableReason.ZERO_REFERENCE_VOLUME: 4,
    }
    emitted_indices = [index for index, bar in enumerate(bars) if bar.is_complete]
    assert cache.row_count == len(emitted_indices)
    protocol = USBaselineProtocol()

    for cache_index, source_index in enumerate(emitted_indices):
        for slot, provenance in enumerate(denominator.candidates):
            expected = evaluate_us_baseline_feature(
                provenance.candidate.compile_feature_spec(),
                bars[: source_index + 1],
                protocol=protocol,
            )
            actual = cache.candidate_values[cache_index, slot]
            reason_code = int(cache.candidate_reason_codes[cache_index, slot])
            if expected.value is None:
                assert np.isnan(actual)
                assert expected.unavailable_reason is not None
                assert reason_code == expected_reason_codes[expected.unavailable_reason]
            else:
                assert reason_code == 0
                assert float(actual).hex() == expected.value.hex()


def test_incomplete_current_bar_is_skipped_before_label_validation_like_r1() -> None:
    execution = compile_us_r2_candidate_execution(_denominator())
    rows = [dict(item) for item in _rows()]
    incomplete_index = next(index for index, bar in enumerate(_bars()) if not bar.is_complete)
    rows[incomplete_index].update(
        {
            "label_available": None,
            "label_value": None,
            "target_available_at": None,
            "unavailable_reason": None,
            "label_row_present": False,
            "source_available_at": None,
            "source_price": None,
        }
    )
    cache = materialize_us_r2_asset_candidate_cache(
        tuple(rows),
        execution,
        expected_asset="AAPL",
    )
    assert cache.row_count == sum(bar.is_complete for bar in _bars())


def test_candidate_cache_keeps_label_unavailability_without_dropping_formation() -> None:
    execution = compile_us_r2_candidate_execution(_denominator())
    cache = materialize_us_r2_asset_candidate_cache(
        _rows(),
        execution,
        expected_asset="AAPL",
    )
    assert cache.row_count > int(cache.label_available.sum())
    unavailable = ~cache.label_available
    assert np.all(np.isnan(cache.label_values[unavailable]))
    assert np.all(cache.label_available_at_us[unavailable] == -1)
    assert np.all(cache.label_reason_codes[unavailable] == 1)


def test_deterministic_wide_npz_is_byte_stable_and_round_trips(tmp_path: Path) -> None:
    execution = compile_us_r2_candidate_execution(_denominator())
    asset_cache = materialize_us_r2_asset_candidate_cache(
        _rows(),
        execution,
        expected_asset="AAPL",
    )
    arrays = combine_us_r2_asset_candidate_caches(
        (asset_cache,),
        candidate_count=FROZEN_CANDIDATE_COUNT,
    )
    first = tmp_path / "first.npz"
    second = tmp_path / "second.npz"
    first_hash, first_size = write_deterministic_us_r2_candidate_npz(first, arrays)
    second_hash, second_size = write_deterministic_us_r2_candidate_npz(second, arrays)

    assert first_hash == second_hash
    assert first_size == second_size
    assert first.read_bytes() == second.read_bytes()
    loaded = load_us_r2_candidate_npz(first, candidate_count=FROZEN_CANDIDATE_COUNT)
    for name, expected in arrays.as_npz_arrays().items():
        actual = loaded.as_npz_arrays()[name]
        assert actual.dtype == expected.dtype
        if np.issubdtype(expected.dtype, np.floating):
            assert np.array_equal(actual, expected, equal_nan=True)
        else:
            assert np.array_equal(actual, expected)


def test_base_panel_batch_gate_reconstructs_full_content_addressed_evidence() -> None:
    years = canonical_us_r2_base_panel_years()
    annual = tuple(
        USR2CompletedAnnualBasePanel(
            year=year,
            plan_id=f"plan-{year}",
            evidence_id=f"evidence-{year}",
            materialization_id=f"materialization-{year}",
            data_version=f"data-{year}",
            row_count=100,
            asset_count=10,
            formation_count=20,
            formation_count_at_minimum_cross_section=10,
            minimum_joint_breadth=10,
            maximum_joint_breadth=10,
            data_size_bytes=1000,
        )
        for year in years
    )
    evidence = USR2BasePanelBatchEvidence(requested_years=years, annual_panels=annual)
    parsed = validate_us_r2_base_panel_batch_gate(
        evidence.to_dict(),
        expected_evidence_id=evidence.evidence_id,
    )
    assert parsed.evidence_id == evidence.evidence_id

    tampered = evidence.to_dict()
    tampered["candidate_dependent_scan"] = True
    with pytest.raises(ValueError):
        validate_us_r2_base_panel_batch_gate(
            tampered,
            expected_evidence_id=evidence.evidence_id,
        )


def test_frozen_denominator_gate_rejects_non_authoritative_37_candidate_fixture() -> None:
    denominator = _denominator()
    assert len(denominator.candidates) == FROZEN_CANDIDATE_COUNT
    with pytest.raises(ValueError, match="exact frozen R1 denominator"):
        validate_us_r2_candidate_denominator(denominator.to_dict())


def test_candidate_operator_has_no_raw_minute_fallback_and_one_parquet_relation() -> None:
    script = Path("scripts/materialize_us_r2_candidate_cache.py").read_text(encoding="utf-8")
    forbidden = (
        "manifest_from_huggingface_snapshot",
        "DuckDBParquetMinuteStore",
        "CalendarSessionizedMinuteStore",
        "MinuteQueryPlan",
        "source_revision",
        "OHLCV-1m",
    )
    for token in forbidden:
        assert token not in script
    assert script.count("read_parquet(") == 1
    assert "raw_minute_source_invocation_count\": 0" in script