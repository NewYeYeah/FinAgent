from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import duckdb
import pytest

from finagent.domain.trading_calendar import TradingCalendarEvidence, TradingSession
from finagent.research import us_r3_economic_campaign as campaign
from finagent.research.us_r3_economics import EconomicPolicy


def fixture_inputs(
    root: Path, *, label: float = 0.0, five_minute: bool = False
) -> tuple[Path, ...]:
    root.mkdir(parents=True, exist_ok=True)
    sessions = tuple(
        TradingSession(
            date(2025, 1, day),
            datetime(2025, 1, day, 14, 30, tzinfo=UTC),
            datetime(2025, 1, day, 21, tzinfo=UTC),
        )
        for day in (2, 3)
    )
    calendar = TradingCalendarEvidence("XNYS", "America/New_York", "fixture", "v1", sessions)
    calendar_path = root / "calendar.json"
    calendar_path.write_text(json.dumps({"passed": True, "evidence": calendar.to_dict()}))
    source = root / "bars.parquet"
    with duckdb.connect() as connection:
        connection.execute("""CREATE TABLE bars (
            slice_id VARCHAR, session_date DATE, session_id VARCHAR, research_asset_id VARCHAR,
            event_time TIMESTAMPTZ, available_at TIMESTAMPTZ,
            open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, volume DOUBLE,
            is_complete BOOLEAN, signal_interval VARCHAR, label_value DOUBLE,
            source_data_version VARCHAR, data_version VARCHAR, robustness_policy_id VARCHAR,
            source_available_at TIMESTAMPTZ, source_price DOUBLE)""")
        rows = []
        for session in sessions:
            for asset in range(4):
                for i in range(26):
                    clock = session.open_at + timedelta(minutes=15 * i)
                    close = 100 + asset * 10 + (asset - 1.5) * i * 0.1 + 0.05 * (i % 3)
                    rows.append(
                        (
                            "decay_15m_30m",
                            session.session_date,
                            "XNYS:" + session.session_date.isoformat(),
                            "A" + str(asset),
                            clock,
                            clock + timedelta(minutes=15),
                            close - 0.05,
                            close + 0.2,
                            close - 0.2,
                            close,
                            1000 + i * 11 + asset * 37,
                            True,
                            "15m",
                            label,
                            "source-v1",
                            "base-v1",
                            "policy-v1",
                            clock + timedelta(minutes=15),
                            close,
                        )
                    )
        if five_minute:
            # Synthetic execution-only rows, never additional feature bars.
            for row in list(rows):
                for step in range(3):
                    execution_row = list(row)
                    execution_row[0] = "frequency_5m_60m"
                    execution_row[4] = row[4] + timedelta(minutes=5 * step)
                    execution_row[5] = execution_row[17] = row[4] + timedelta(
                        minutes=5 * (step + 1)
                    )
                    execution_row[12] = "5m"
                    rows.append(tuple(execution_row))
        connection.executemany(
            "INSERT INTO bars VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        connection.execute("COPY bars TO ? (FORMAT PARQUET)", [str(source)])
    base_plan = root / "base_plan.json"
    base_plan.write_text(
        json.dumps(
            {
                "plan_id": "plan-v1",
                "policy_id": "policy-v1",
                "year": 2025,
                "calendar_id": calendar.calendar_id,
                "source_data_version": "source-v1",
                "data_version": "base-v1",
            }
        )
    )
    evidence = root / "evidence.json"
    evidence.write_text(
        json.dumps(
            {
                "passed": True,
                "blockers": [],
                "plan_id": "plan-v1",
                "policy_id": "policy-v1",
                "year": 2025,
                "row_count": len(rows),
            }
        )
    )
    return source, calendar_path, base_plan, evidence


def freeze(root: Path, **kwargs) -> Path:
    inputs = fixture_inputs(root / "inputs", **kwargs)
    path = root / "protocol.json"
    campaign.freeze_campaign(
        *inputs,
        path,
        start=date(2025, 1, 2),
        end=date(2025, 1, 3),
        policy=EconomicPolicy(minimum_breadth=3, selection_count=1),
    )
    return path


def test_real_parquet_all_strategies_costs_and_zero_scan_resume(tmp_path, monkeypatch) -> None:
    protocol = freeze(tmp_path)
    result = campaign.run_campaign(protocol, tmp_path / "out")
    assert result["evaluated_sessions"] == 2
    assert result["terminal"] == "EXPLORATORY_COMPLETE"
    assert len(result["summary"]) == 7
    assert all(len(grid) == 4 for grid in result["summary"].values())
    assert result["summary"]["cash"]["10.0"]["compounded_return"] == 0
    assert all(result[k] is False for k in campaign.AUTHORITY)
    saved = (tmp_path / "out/summary.json").read_bytes()

    def no_scan(*args):
        pytest.fail("completed campaign must resume with zero Parquet scans")

    monkeypatch.setattr(campaign, "iter_feature_sessions", no_scan)
    monkeypatch.setattr(campaign, "iter_execution_sessions", no_scan)
    resumed = campaign.run_campaign(protocol, tmp_path / "out")
    assert resumed["resumed_sessions"] == 2
    assert resumed["evaluated_sessions"] == 0
    assert resumed["evidence_id"] == result["evidence_id"]
    assert saved == (tmp_path / "out/summary.json").read_bytes()


def test_five_minute_campaign_preserves_signals_and_binds_coverage(tmp_path) -> None:
    inputs = fixture_inputs(tmp_path / "inputs", five_minute=True)
    results = []
    for profile in ("strict_15m", "pending_exit_5m"):
        root = tmp_path / profile
        protocol = root / "protocol.json"
        campaign.freeze_campaign(
            *inputs,
            protocol,
            start=date(2025, 1, 2),
            end=date(2025, 1, 3),
            policy=EconomicPolicy(minimum_breadth=3, selection_count=1, execution_profile=profile),
        )
        results.append(campaign.run_campaign(protocol, root))
    for name, grid in results[0]["summary"].items():
        for cost, summary in grid.items():
            assert (
                results[1]["summary"][name][cost]["compounded_return"]
                == summary["compounded_return"]
            )
    day = json.loads((tmp_path / "pending_exit_5m/sessions/2025-01-02.json").read_text())
    assert day["execution_reference_coverage"]["A0"] == {
        "expected": 78,
        "observed": 78,
        "explicit_missing": 0,
    }


def test_pending_profile_requires_authentic_execution_slice(tmp_path) -> None:
    inputs = fixture_inputs(tmp_path / "inputs")
    with pytest.raises(ValueError, match="required feature/execution slice"):
        campaign.freeze_campaign(
            *inputs,
            tmp_path / "protocol.json",
            start=date(2025, 1, 2),
            end=date(2025, 1, 3),
            policy=EconomicPolicy(
                minimum_breadth=3, selection_count=1, execution_profile="pending_exit_5m"
            ),
        )


def opening_protocol(root: Path) -> Path:
    inputs = fixture_inputs(root / "inputs", five_minute=True)
    protocol = root / "protocol.json"
    campaign.freeze_campaign(
        *inputs,
        protocol,
        start=date(2025, 1, 2),
        end=date(2025, 1, 3),
        policy=EconomicPolicy(
            minimum_breadth=3, selection_count=1, execution_profile="pending_exit_5m"
        ),
        experiment="low_turnover_opening",
    )
    return protocol


def test_opening_campaign_freezes_ten_arms_compares_and_resumes(tmp_path, monkeypatch) -> None:
    protocol = opening_protocol(tmp_path)
    frozen = json.loads(protocol.read_text())
    assert frozen["opening_experiment"]["primary_cost_bps"] == 5.0
    assert len(frozen["opening_experiment"]["new_mechanisms"]) == 2
    assert len(frozen["strategies"]) == 10
    assert all(
        frozen["allocation_schedules"][name] == "rolling_sleeves"
        for name in campaign.strategy_ids()
    )
    result = campaign.run_campaign(protocol, tmp_path / "out")
    day = json.loads((tmp_path / "out/sessions/2025-01-02.json").read_text())
    assert result["terminal"] == "EXPLORATORY_COMPLETE"
    for name in campaign.OPENING_ARMS:
        for row in day["results"][name].values():
            assert row["entries"] == 1
            assert row["ledger"][14]["decision_bar_index"] == 3
            assert row["ledger"][13]["shares"] == {}
    pair = result["opening_paired_comparisons"]["opening_60m_momentum"]["opening_60m_equal_weight"][
        "5.0"
    ]
    expected = (
        result["summary"]["opening_60m_momentum"]["5.0"]["compounded_return"]
        - result["summary"]["opening_60m_equal_weight"]["5.0"]["compounded_return"]
    )
    assert pair["compounded_return_difference"] == expected
    monkeypatch.setattr(campaign, "iter_feature_sessions", lambda *args: pytest.fail("no rescan"))
    monkeypatch.setattr(campaign, "iter_execution_sessions", lambda *args: pytest.fail("no rescan"))
    resumed = campaign.run_campaign(protocol, tmp_path / "out")
    assert resumed["evidence_id"] == result["evidence_id"]
    assert resumed["evaluated_sessions"] == 0


def test_opening_comparison_with_missing_exit_is_unavailable(tmp_path, monkeypatch) -> None:
    protocol = opening_protocol(tmp_path)
    original = campaign.iter_execution_sessions

    def absent_exit(source, profile):
        for day, marks in original(source, profile):
            yield (
                day,
                {
                    key: (None if key[1].hour >= 20 and key[1].minute >= 45 else price)
                    for key, price in marks.items()
                },
            )

    monkeypatch.setattr(campaign, "iter_execution_sessions", absent_exit)
    result = campaign.run_campaign(protocol, tmp_path / "out")
    assert result["terminal"] == "EXPLORATORY_INCOMPLETE_EVIDENCE"
    pair = result["opening_paired_comparisons"]["opening_60m_momentum"]["cash"]["5.0"]
    assert pair["scheduled_sessions"] == 2
    assert pair["mean_daily_excess_bps"] is None
    assert pair["compounded_return_difference"] is None


def test_opening_signal_uses_only_frozen_clock_and_complete_opening_history(tmp_path) -> None:
    inputs = fixture_inputs(tmp_path, five_minute=True)
    _, assets, _ = next(campaign.iter_feature_sessions(inputs[0]))
    policy = EconomicPolicy(minimum_breadth=3, selection_count=1)
    targets = campaign.session_targets(assets, policy, "low_turnover_opening")
    for name, parent in campaign.OPENING_ARMS.items():
        assert targets[name][3] == targets[parent][3]
        assert all(not v for i, v in enumerate(targets[name]) if i != 3)
    missing = tuple(
        replace(a, bars=(replace(a.bars[0], is_complete=False),) + a.bars[1:]) for a in assets
    )
    unavailable = campaign.session_targets(missing, policy, "low_turnover_opening")
    assert unavailable["opening_60m_momentum"] == [{}] * 26
    assert unavailable["opening_60m_relative_momentum"] == [{}] * 26


def activity_protocol(root: Path) -> Path:
    inputs = fixture_inputs(root / "inputs", five_minute=True)
    source, calendar_path, base_plan, evidence = inputs
    old_calendar = campaign._calendar(calendar_path)
    prior = tuple(
        TradingSession(
            date(2024, 12, d),
            datetime(2024, 12, d, 14, 30, tzinfo=UTC),
            datetime(2024, 12, d, 21, tzinfo=UTC),
        )
        for d in range(2, 22)
    )
    calendar = TradingCalendarEvidence(
        "XNYS", "America/New_York", "fixture", "v1", prior + old_calendar.sessions
    )
    calendar_path.write_text(json.dumps({"passed": True, "evidence": calendar.to_dict()}))
    bp = json.loads(base_plan.read_text())
    bp["calendar_id"] = calendar.calendar_id
    base_plan.write_text(json.dumps(bp))
    history = root / "history.parquet"
    with duckdb.connect() as c:
        c.execute(
            "CREATE TABLE x AS SELECT * FROM read_parquet(?) WHERE slice_id='decay_15m_30m' AND session_date='2025-01-02'",
            [str(source)],
        )
        c.execute(
            """COPY (SELECT x.* REPLACE (
            CAST(d AS DATE) AS session_date, 'XNYS:' || CAST(CAST(d AS DATE) AS VARCHAR) AS session_id,
            event_time + (d - TIMESTAMP '2025-01-02') AS event_time,
            available_at + (d - TIMESTAMP '2025-01-02') AS available_at,
            source_available_at + (d - TIMESTAMP '2025-01-02') AS source_available_at,
            100.0 AS volume)
            FROM x CROSS JOIN generate_series(TIMESTAMP '2024-12-02', TIMESTAMP '2024-12-21', INTERVAL 1 DAY) days(d)) TO ? (FORMAT PARQUET)""",
            [str(history)],
        )
        count = c.execute("SELECT count(*) FROM read_parquet(?)", [str(history)]).fetchone()[0]
    hp, he = root / "history_plan.json", root / "history_evidence.json"
    hp.write_text(json.dumps({**bp, "year": 2024}))
    he.write_text(
        json.dumps({**json.loads(evidence.read_text()), "year": 2024, "row_count": count})
    )
    protocol = root / "protocol.json"
    campaign.freeze_campaign(
        *inputs,
        protocol,
        start=date(2025, 1, 2),
        end=date(2025, 1, 3),
        policy=EconomicPolicy(
            minimum_breadth=3, selection_count=1, execution_profile="pending_exit_5m"
        ),
        experiment="activity_reversal",
        history_source=history,
        history_base_plan=hp,
        history_base_evidence=he,
    )
    return protocol


def test_activity_cross_year_partial_resume_and_history_binding(tmp_path, monkeypatch):
    protocol = activity_protocol(tmp_path)
    frozen = json.loads(protocol.read_text())
    assert len(frozen["strategies"]) == 13
    assert len(frozen["activity_experiment"]["warmup_sessions"]) == 20

    def interrupt(event, fields):
        raise RuntimeError("interrupted after persistence")

    with pytest.raises(RuntimeError, match="interrupted"):
        campaign.run_campaign(protocol, tmp_path / "out", progress=interrupt)
    resumed = campaign.run_campaign(protocol, tmp_path / "out")
    clean = campaign.run_campaign(protocol, tmp_path / "clean")
    assert resumed["resumed_sessions"] == 1
    assert resumed["evidence_id"] == clean["evidence_id"]
    first = json.loads((tmp_path / "out/sessions/2025-01-02.json").read_text())
    assert first["activity_ratios"]["A0"][0] == 10.0
    assert first["results"]["activity_relative_reversal"]["5.0"]["entries"] == 1
    monkeypatch.setattr(
        campaign, "iter_feature_sessions", lambda *args: pytest.fail("no scan on full resume")
    )
    assert campaign.run_campaign(protocol, tmp_path / "out")["evaluated_sessions"] == 0
    with (tmp_path / "history.parquet").open("ab") as handle:
        handle.write(b"changed")
    with pytest.raises(ValueError, match="bound input changed"):
        campaign.run_campaign(protocol, tmp_path / "out")


def test_source_and_evidence_tampering_fail_closed(tmp_path) -> None:
    protocol = freeze(tmp_path)
    campaign.run_campaign(protocol, tmp_path / "out")
    path = tmp_path / "out/sessions/2025-01-02.json"
    data = json.loads(path.read_text())
    data["results"]["cash"]["0.0"]["net_return"] = 123
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="content identity"):
        campaign.run_campaign(protocol, tmp_path / "out")
    source = tmp_path / "inputs/bars.parquet"
    with source.open("ab") as handle:
        handle.write(b"changed")
    with pytest.raises(ValueError, match="bound input"):
        campaign.run_campaign(protocol, tmp_path / "out")


def test_interrupt_and_resume_preserve_completed_sessions(tmp_path) -> None:
    protocol = freeze(tmp_path)

    def stop(event, fields):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        campaign.run_campaign(protocol, tmp_path / "out", progress=stop)
    old = (tmp_path / "out/sessions/2025-01-02.json").read_bytes()
    result = campaign.run_campaign(protocol, tmp_path / "out")
    assert result["resumed_sessions"] == 1
    assert result["evaluated_sessions"] == 1
    assert old == (tmp_path / "out/sessions/2025-01-02.json").read_bytes()


def test_forward_labels_do_not_change_trading_results(tmp_path) -> None:
    first = campaign.run_campaign(freeze(tmp_path / "a", label=999), tmp_path / "a/out")
    second = campaign.run_campaign(freeze(tmp_path / "b", label=-999), tmp_path / "b/out")
    assert first["summary"] == second["summary"]


def test_future_mutation_does_not_change_earlier_features_and_missing_open_is_not_inferred(
    tmp_path,
) -> None:
    inputs = fixture_inputs(tmp_path)
    _day, assets, _ = next(campaign.iter_feature_sessions(inputs[0]))
    calendar = campaign._calendar(inputs[1])
    aligned = campaign.aligned_session(assets, calendar.sessions[0], [a.asset_id for a in assets])
    changed = tuple(
        replace(
            a,
            bars=a.bars[:15]
            + tuple(
                replace(b, close=b.close * 10, high=b.high * 10, low=b.low * 10, open=b.open * 10)
                for b in a.bars[15:]
            ),
        )
        for a in aligned
    )
    policy = EconomicPolicy(minimum_breadth=3, selection_count=1)
    first, second = [campaign.session_targets(a, policy) for a in (aligned, changed)]
    assert all(first[name][:15] == second[name][:15] for name in first)
    absent_open = tuple(replace(a, bars=a.bars[1:]) for a in assets)
    padded = campaign.aligned_session(
        absent_open, calendar.sessions[0], [a.asset_id for a in assets]
    )
    assert not padded[0].bars[0].is_complete
    assert campaign.session_targets(padded, policy)["session_relative_momentum"] == [{}] * 26


def test_missing_calendar_session_remains_in_denominator(tmp_path, monkeypatch) -> None:
    protocol = freeze(tmp_path)
    original = campaign.iter_feature_sessions
    original_marks = campaign.iter_execution_sessions

    def only_first_feature(source):
        yield next(original(source))

    def only_first_marks(source, profile):
        yield next(original_marks(source, profile))

    monkeypatch.setattr(campaign, "iter_feature_sessions", only_first_feature)
    monkeypatch.setattr(campaign, "iter_execution_sessions", only_first_marks)
    result = campaign.run_campaign(protocol, tmp_path / "out")
    assert result["terminal"] == "EXPLORATORY_INCOMPLETE_EVIDENCE"
    assert result["summary"]["cash"]["0.0"]["scheduled_sessions"] == 2
    assert result["summary"]["cash"]["0.0"]["compounded_return"] is None


def test_execution_anchor_is_independent_of_feature_completeness(tmp_path) -> None:
    source, *_ = fixture_inputs(tmp_path)
    changed = tmp_path / "changed.parquet"
    with duckdb.connect() as c:
        c.execute("CREATE TABLE x AS SELECT * FROM read_parquet(?)", [str(source)])
        c.execute("UPDATE x SET is_complete=false, close=999999")
        c.execute("COPY x TO ? (FORMAT PARQUET)", [str(changed)])
    first, second = [list(campaign.iter_execution_sessions(path)) for path in (source, changed)]
    assert first == second
    assert all(price is not None for _, marks in second for price in marks.values())
    assert "label_value" not in campaign.EXECUTION_QUERY
    assert "target_available_at" not in campaign.EXECUTION_QUERY


def test_execution_anchor_rejects_future_timestamp(tmp_path) -> None:
    source, *_ = fixture_inputs(tmp_path)
    changed = tmp_path / "changed.parquet"
    with duckdb.connect() as c:
        c.execute("CREATE TABLE x AS SELECT * FROM read_parquet(?)", [str(source)])
        c.execute("UPDATE x SET source_available_at=available_at + INTERVAL 1 MINUTE")
        c.execute("COPY x TO ? (FORMAT PARQUET)", [str(changed)])
    with pytest.raises(ValueError, match="exact clock"):
        list(campaign.iter_execution_sessions(changed))


def test_cli_run_uses_same_frozen_protocol(tmp_path) -> None:
    protocol = freeze(tmp_path)
    run = subprocess.run(
        [
            sys.executable,
            "scripts/run_us_r3_economic_screen.py",
            "run",
            "--protocol",
            str(protocol),
            "--output-root",
            str(tmp_path / "out"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout)["evaluated_sessions"] == 2
    assert "session_complete" in run.stderr


def test_half_day_and_late_availability_use_calendar_not_observed_extent(tmp_path) -> None:
    inputs = fixture_inputs(tmp_path)
    _, assets, _ = next(campaign.iter_feature_sessions(inputs[0]))
    full = campaign._calendar(inputs[1]).sessions[0]
    half = replace(full, close_at=full.open_at + timedelta(minutes=210), is_half_day=True)
    shortened = tuple(replace(a, bars=a.bars[:14]) for a in assets)
    aligned = campaign.aligned_session(shortened, half, [a.asset_id for a in assets])
    assert len(aligned[0].bars) == 14
    bad = replace(
        shortened[0],
        bars=(replace(shortened[0].bars[0], available_at=full.close_at),) + shortened[0].bars[1:],
    )
    with pytest.raises(ValueError, match="availability"):
        campaign.aligned_session((bad,) + shortened[1:], half, [a.asset_id for a in assets])
