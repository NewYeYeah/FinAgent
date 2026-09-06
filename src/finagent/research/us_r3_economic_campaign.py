"""Frozen, bounded, exposed-data economic screen; never an independent Alpha Gate."""

from __future__ import annotations

import hashlib
import json
import math
import tempfile
from collections.abc import Callable, Generator, Mapping
from contextlib import closing
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from finagent.domain.trading_calendar import TradingCalendarEvidence, TradingSession
from finagent.research.us_a1_factor_materialization import compile_factor_graph_batch
from finagent.research.us_a1_factor_panel_materialization import (
    FactorPanelAsset,
    materialize_compiled_factor_panel,
)
from finagent.research.us_baselines import USBaselineBar
from finagent.research.us_r3_activity import ACTIVITY_ARMS, ActivityHistory, activity_targets
from finagent.research.us_r3_alpha_catalog import build_us_r3_executable_frontier_candidates
from finagent.research.us_r3_economics import (
    EconomicPolicy,
    positive_weights,
    simulate_session,
    summarize_sessions,
)
from finagent.research.us_r3_usability import (
    implementation_identity as feature_implementation_identity,
)
from finagent.research.us_r3_usability import (
    iter_feature_sessions,
    write_immutable_json,
)

Progress = Callable[[str, Mapping[str, object]], None]
ExecutionMarks = dict[tuple[str, datetime], float | None]
# Only the source side of the existing D2 label join is read. Future target
# prices, target clocks, label availability and outcomes are never projected.
EXECUTION_QUERY = """
SELECT CAST(session_date AS VARCHAR), research_asset_id, epoch(available_at),
       epoch(source_available_at), source_price
FROM read_parquet(?) WHERE slice_id = 'decay_15m_30m'
ORDER BY session_date, research_asset_id, available_at
"""
AUTHORITY = {
    "alpha_authority": False,
    "alpha_gate_evaluated": False,
    "execution_authority": False,
    "order_authority": False,
    "paper_authority": False,
    "live_capital_authority": False,
    "independent_confirmation": False,
    "agent_value_evaluated": False,
}


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode()
    ).hexdigest()


def file_digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def code_identity() -> str:
    root = Path(__file__).parent
    return digest(
        {
            "features": feature_implementation_identity(),
            "economics": file_digest(root / "us_r3_economics.py"),
            "activity": file_digest(root / "us_r3_activity.py"),
            "campaign": file_digest(Path(__file__)),
            "calendar": file_digest(root.parent / "domain/trading_calendar.py"),
        }
    )


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError("expected JSON object")
    return value


def _sealed(path: Path, key: str, prefix: str) -> dict[str, Any]:
    value = _load(path)
    if value.get(key) != prefix + digest({k: v for k, v in value.items() if k != key}):
        raise ValueError(f"content identity mismatch: {path}")
    return value


def _calendar(path: Path) -> TradingCalendarEvidence:
    report = _load(path)
    if report.get("passed") is not True:
        raise ValueError("calendar report must pass")
    raw = report["evidence"]
    sessions = tuple(
        TradingSession(
            session_date=date.fromisoformat(row["session_date"]),
            open_at=datetime.fromisoformat(row["open_at"]),
            close_at=datetime.fromisoformat(row["close_at"]),
            pre_open_at=datetime.fromisoformat(row["pre_open_at"]) if row["pre_open_at"] else None,
            post_close_at=datetime.fromisoformat(row["post_close_at"])
            if row["post_close_at"]
            else None,
            is_half_day=row["is_half_day"],
        )
        for row in raw["sessions"]
    )
    result = TradingCalendarEvidence(
        raw["market_id"],
        raw["timezone"],
        raw["source"],
        raw["source_revision"],
        sessions,
        raw["regular_session_minutes"],
    )
    if result.calendar_id != raw["calendar_id"] or result.market_id != "XNYS":
        raise ValueError("calendar content identity mismatch")
    return result


OPENING_ARMS = {
    "opening_60m_momentum": "session_momentum_ablation",
    "opening_60m_relative_momentum": "session_relative_momentum",
    "opening_60m_equal_weight": "eligible_equal_weight",
}


def strategy_ids(experiment: str = "sleeve_baseline") -> tuple[str, ...]:
    if experiment not in ("sleeve_baseline", "low_turnover_opening", "activity_reversal"):
        raise ValueError("unsupported economic experiment")
    baseline = tuple(
        item.strategy.slug for item in build_us_r3_executable_frontier_candidates()
    ) + (
        "session_relative_momentum",
        "session_momentum_ablation",
        "eligible_equal_weight",
        "cash",
    )
    if experiment == "activity_reversal":
        return baseline + tuple(OPENING_ARMS) + ACTIVITY_ARMS
    return baseline + tuple(OPENING_ARMS) if experiment == "low_turnover_opening" else baseline


def freeze_campaign(
    source: Path,
    calendar_path: Path,
    base_plan_path: Path,
    base_evidence_path: Path,
    output: Path,
    *,
    start: date,
    end: date,
    policy: EconomicPolicy | None = None,
    experiment: str = "sleeve_baseline",
    history_source: Path | None = None,
    history_base_plan: Path | None = None,
    history_base_evidence: Path | None = None,
) -> dict[str, Any]:
    """Inspect metadata only, then persist scope before any new performance read.

    This binds locally trusted R2 engineering artifacts. It does not authenticate
    the upstream provider, restore PIT universe history, or admit an Agent to data.
    """
    import duckdb

    policy = policy or EconomicPolicy()
    names = strategy_ids(experiment)
    if experiment in ("low_turnover_opening", "activity_reversal") and (
        policy.execution_profile != "pending_exit_5m"
        or policy.delay_bars != 1
        or policy.holding_bars != 4
        or policy.cost_bps != (0.0, 1.0, 5.0, 10.0)
    ):
        raise ValueError("opening experiment requires the preserved delay/holding/cost/exit policy")
    if start > end or start.year != end.year:
        raise ValueError("one bounded annual development window required")
    calendar = _calendar(calendar_path)
    sessions = [s for s in calendar.sessions if start <= s.session_date <= end]
    if not sessions or not calendar.covers(start) or not calendar.covers(end):
        raise ValueError("calendar does not cover requested development window")
    base_plan, evidence = _load(base_plan_path), _load(base_evidence_path)
    if (
        evidence.get("passed") is not True
        or evidence.get("blockers") != []
        or evidence.get("plan_id") != base_plan.get("plan_id")
        or evidence.get("policy_id") != base_plan.get("policy_id")
        or evidence.get("year") != start.year
        or base_plan.get("year") != start.year
        or base_plan.get("calendar_id") != calendar.calendar_id
    ):
        raise ValueError("local R2 source/calendar evidence mismatch")
    inputs = {
        name: {"path": str(path.resolve()), "sha256": file_digest(path)}
        for name, path in (
            ("source", source),
            ("calendar", calendar_path),
            ("base_plan", base_plan_path),
            ("base_evidence", base_evidence_path),
        )
    }
    with duckdb.connect(config={"memory_limit": "256MiB", "threads": "1"}) as connection:
        metadata = connection.execute(
            "SELECT source_data_version, data_version, robustness_policy_id, count(*) "
            "FROM read_parquet(?) GROUP BY ALL",
            [str(source)],
        ).fetchall()
        expected = [
            (
                base_plan["source_data_version"],
                base_plan["data_version"],
                base_plan["policy_id"],
                evidence["row_count"],
            )
        ]
        if metadata != expected:
            raise ValueError("Parquet versions/row count do not match local R2 evidence")
        required_slice = (
            "frequency_5m_60m" if policy.execution_profile == "pending_exit_5m" else "decay_15m_30m"
        )
        slices = {
            row[0]
            for row in connection.execute(
                "SELECT DISTINCT slice_id FROM read_parquet(?)", [str(source)]
            ).fetchall()
        }
        if not {required_slice, "decay_15m_30m"} <= slices:
            raise ValueError("source lacks required feature/execution slice")
        universe = [
            row[0]
            for row in connection.execute(
                "SELECT DISTINCT research_asset_id FROM read_parquet(?) ORDER BY 1", [str(source)]
            ).fetchall()
        ]
    if not policy.minimum_breadth <= len(universe) <= 256:
        raise ValueError("source universe cannot satisfy frozen breadth")
    history_dates: list[str] = []
    if experiment == "activity_reversal":
        if history_source is None or history_base_plan is None or history_base_evidence is None:
            raise ValueError("activity experiment requires bound prior-year history inputs")
        prior = [s for s in calendar.sessions if s.session_date < sessions[0].session_date][-20:]
        if len(prior) != 20 or any(s.session_date.year != start.year - 1 for s in prior):
            raise ValueError(
                "activity window must start at the year's first session with 20 prior-year calendar sessions"
            )
        history_dates = [s.session_date.isoformat() for s in prior]
        hp, he = _load(history_base_plan), _load(history_base_evidence)
        if (
            he.get("passed") is not True
            or he.get("blockers") != []
            or he.get("plan_id") != hp.get("plan_id")
            or he.get("policy_id") != hp.get("policy_id")
            or he.get("year") != start.year - 1
            or hp.get("year") != start.year - 1
            or hp.get("calendar_id") != calendar.calendar_id
        ):
            raise ValueError("history R2/calendar evidence mismatch")
        for name, path in (
            ("history_source", history_source),
            ("history_base_plan", history_base_plan),
            ("history_base_evidence", history_base_evidence),
        ):
            inputs[name] = {"path": str(path.resolve()), "sha256": file_digest(path)}
        with duckdb.connect(config={"memory_limit": "256MiB", "threads": "1"}) as c:
            actual = c.execute(
                "SELECT source_data_version, data_version, robustness_policy_id, count(*) FROM read_parquet(?) GROUP BY ALL",
                [str(history_source)],
            ).fetchall()
            if actual != [
                (hp["source_data_version"], hp["data_version"], hp["policy_id"], he["row_count"])
            ]:
                raise ValueError("history Parquet versions/row count mismatch")
            if not c.execute(
                "SELECT count(*) FROM read_parquet(?) WHERE slice_id='decay_15m_30m'",
                [str(history_source)],
            ).fetchone()[0]:
                raise ValueError("history requires the feature slice")
    elif any(p is not None for p in (history_source, history_base_plan, history_base_evidence)):
        raise ValueError("history inputs require activity experiment")
    for binding in inputs.values():
        if file_digest(Path(binding["path"])) != binding["sha256"]:
            raise ValueError("source changed during freeze")
    payload: dict[str, Any] = {
        "schema_version": "finagent.us-r3-economic-protocol.v5",
        "inputs": inputs,
        "implementation_id": code_identity(),
        "policy": asdict(policy),
        "start": start.isoformat(),
        "end": end.isoformat(),
        "sessions": [s.session_date.isoformat() for s in sessions],
        "universe": universe,
        "experiment": experiment,
        "strategies": list(names),
        "allocation_schedules": {
            name: "first_activity_once"
            if name in ACTIVITY_ARMS
            else ("opening_60m_once" if name in OPENING_ARMS else "rolling_sleeves")
            for name in names
        },
        "activity_experiment": {
            "warmup_sessions": history_dates,
            "history": "previous 20 calendar sessions; same 15m slot since local open; current session excluded; all 20 complete observations required; positive median denominator",
            "mechanism": "relative volume >=2 and current 15m return below valid-universe mean; positive relative reversal scores top-five equal weight",
            "budget": "one attempted basket/day after open+60m; 15m delay; full cash including fees; hold 60m; scheduled exit no later than close-15m; missing entry cancels day",
            "controls": "same-history-admission reversal without volume condition; broad eligible equal-weight at identical conditional trigger; retain all previous ten arms",
            "new_mechanism_count": 1,
            "primary_cost_bps": 5.0,
            "stop_rule": "one fixed run; no parameter sweep; retain cash days and failures; no automatic selection or Alpha",
            "followup_rule": "follow-up only if complete 5bp compounded return is positive and paired mean daily excess is positive versus both activity ablation and trigger-matched equal-weight; otherwise stop this rule; unresolved evidence is inconclusive",
        }
        if experiment == "activity_reversal"
        else None,
        "opening_experiment": {
            "new_mechanisms": ["opening_60m_momentum", "opening_60m_relative_momentum"],
            "matched_control": "opening_60m_equal_weight",
            "decision_minutes_after_open": 60,
            "entry_minutes_after_open": 75,
            "capital": "one cash-limited full-NAV basket, buy fees included; fixed shares; no replenishment",
            "exit_minutes_before_close": 15,
            "missing_entry": "cancel entire basket for the day; no retries",
            "primary_cost_bps": 5.0,
            "primary_diagnostics": "net compound return; paired daily return excess vs matched equal-weight and cash",
            "inference": "descriptive exposed data; no significance or automatic selection",
        }
        if experiment in ("low_turnover_opening", "activity_reversal")
        else None,
        "prototype_ids": [c.candidate_id for c in build_us_r3_executable_frontier_candidates()],
        "search_budget": f"one fixed run; all {len(names)} arms and all cost scenarios retained; no parameter sweep",
        "selection": "positive top-k equal allocation; positive rank centered at 0.5",
        "mechanism": "same-day open-to-current return, with/without contemporaneous universe mean",
        "exposure": "R2 corpus already exposed; development/exploratory only",
        "source_admission_scope": "local R2 artifact/version binding; upstream provenance not reauthenticated",
        "universe_scope": "fixed current-symbol engineering universe; survivorship conditioned",
        "execution": "one full 15m bar delay; hypothetical close references; long-only; no borrow",
        "execution_price_profile": "causal_raw_1m_source_anchor_v2; separate from feature completeness",
        "missing_exit_policy": (
            "retry each 5m at that clock's authentic source anchor; retain unfilled shares/cash; "
            "sell available legs; suppress new baskets while any due exit remains; "
            "last scheduled exit close-minus-15m; hard cutoff close-minus-5m; "
            "unfilled positions invalidate the session; no closing-auction fill"
            if policy.execution_profile == "pending_exit_5m"
            else "missing due exit invalidates session"
        ),
        "execution_slice": "frequency_5m_60m"
        if policy.execution_profile == "pending_exit_5m"
        else "decay_15m_30m",
        "cost_scope": "bps per gross net-traded notional; scenario assumptions, not measured spreads",
        "accounting": "fixed daily-opening NAV sleeve budget; share netting; cash limited; intraday flat",
        "primary_endpoint": "full-period daily-compounded net return by strategy and cost scenario",
        "diagnostics": [
            "daily-close drawdown",
            "gross turnover",
            "cash periods",
            "unresolved marks",
            "zero-cost linear break-even",
            "mechanism ablation",
            "daily-return correlation",
        ],
        "stopping_rule": "one fixed calendar window; no adaptive extension, selection, or refit",
        "independent_sample": "not admitted; final significance/power/stopping protocol still required",
        "acceptance": "exploratory screen only; positive sample returns never grant Alpha",
        **AUTHORITY,
    }
    payload["protocol_id"] = "us-r3-economic-protocol-" + digest(payload)
    write_immutable_json(output, payload)
    return payload


def iter_execution_sessions(
    source: Path, execution_profile: str = "strict_15m"
) -> Generator[tuple[str, ExecutionMarks], None, None]:
    import duckdb

    with (
        tempfile.TemporaryDirectory(prefix="finagent-r3-marks-") as spill,
        duckdb.connect(config={"memory_limit": "256MiB", "threads": "1"}) as connection,
    ):
        connection.execute("SET temp_directory = ?", [spill])
        connection.execute("SET max_temp_directory_size = '1GiB'")
        if execution_profile not in ("strict_15m", "pending_exit_5m"):
            raise ValueError("unsupported execution profile")
        query = EXECUTION_QUERY
        if execution_profile == "pending_exit_5m":
            query = query.replace("decay_15m_30m", "frequency_5m_60m")
        connection.execute(query, [str(source)])
        current: str | None = None
        marks: ExecutionMarks = {}
        while batch := connection.fetchmany(512):
            for day, asset, available, source_available, price in batch:
                if not isinstance(day, str) or not isinstance(asset, str):
                    raise TypeError("invalid execution reference identity")
                if current is not None and day != current:
                    yield current, marks
                    marks = {}
                current = day
                key = (asset, datetime.fromtimestamp(available, UTC))
                if key in marks or len(marks) >= 256 * 192:
                    raise ValueError("duplicate or unbounded execution marks")
                if price is None:
                    if source_available is not None:
                        raise ValueError("partial source price identity")
                    marks[key] = None
                else:
                    if source_available != available or not math.isfinite(price) or price <= 0:
                        raise ValueError(
                            "execution anchor must be positive and available at the exact clock"
                        )
                    marks[key] = float(price)
        if current is not None:
            yield current, marks


def aligned_session(
    assets: tuple[FactorPanelAsset, ...],
    session: TradingSession,
    universe: list[str],
) -> tuple[FactorPanelAsset, ...]:
    count = session.regular_minutes // 15
    if session.regular_minutes % 15 or not 3 <= count <= 64:
        raise ValueError("unsupported session duration")
    clocks = tuple(session.open_at + timedelta(minutes=15 * i) for i in range(count))
    by_asset = {asset.asset_id: asset for asset in assets}
    if len(by_asset) != len(assets) or not set(by_asset) <= set(universe):
        raise ValueError("unexpected or duplicate session asset")
    aligned = []
    session_ids = {bar.session_id for asset in assets for bar in asset.bars}
    if len(session_ids) > 1:
        raise ValueError("mixed session identity")
    sid = next(iter(session_ids), "missing:" + session.session_date.isoformat())
    for asset in universe:
        bars = by_asset[asset].bars if asset in by_asset else ()
        index = {bar.event_time: bar for bar in bars}
        if len(index) != len(bars) or not set(index) <= set(clocks):
            raise ValueError("bars outside accepted calendar or duplicate clock")
        if any(bar.available_at != bar.event_time + timedelta(minutes=15) for bar in bars):
            raise ValueError("unexpected causal close availability")
        aligned.append(
            FactorPanelAsset(
                asset,
                tuple(
                    index.get(clock)
                    or USBaselineBar(
                        event_time=clock,
                        available_at=clock + timedelta(minutes=15),
                        session_id=sid,
                        open=1.0,
                        high=1.0,
                        low=1.0,
                        close=1.0,
                        volume=0.0,
                        is_complete=False,
                    )
                    for clock in clocks
                ),
            )
        )
    return tuple(aligned)


def session_targets(
    assets: tuple[FactorPanelAsset, ...],
    policy: EconomicPolicy,
    experiment: str = "sleeve_baseline",
) -> dict[str, list[dict[str, float]]]:
    candidates = build_us_r3_executable_frontier_candidates()
    compiled = compile_factor_graph_batch(
        tuple(c.graph for c in candidates), admit_panel_operators=True
    )
    panel = materialize_compiled_factor_panel(
        compiled, assets, minimum_cross_section=policy.minimum_breadth
    )
    series = {(row.candidate_id, row.asset_id): row.values for row in panel.candidates}
    targets: dict[str, list[dict[str, float]]] = {name: [] for name in strategy_ids()}
    anchor_valid = {asset.asset_id: True for asset in assets}
    for i in range(len(assets[0].bars)):
        for candidate in candidates:
            scores = {
                asset.asset_id: series[candidate.candidate_id, asset.asset_id][i]
                for asset in assets
            }
            if candidate.strategy.slug == "volume-conditioned-liquidity-reversal":
                scores = {
                    asset: value - 0.5 if value is not None else None
                    for asset, value in scores.items()
                }
            targets[candidate.strategy.slug].append(positive_weights(scores, policy))
        anchor: dict[str, float | None] = {}
        eligible: dict[str, float | None] = {}
        for asset in assets:
            bar = asset.bars[i]
            anchor_valid[asset.asset_id] &= bar.is_complete
            anchor[asset.asset_id] = (
                bar.close / asset.bars[0].open - 1.0 if anchor_valid[asset.asset_id] else None
            )
            eligible[asset.asset_id] = 1.0 if bar.is_complete else None
        valid = [v for v in anchor.values() if v is not None]
        mean = math.fsum(valid) / len(valid) if valid else 0.0
        relative = {a: v - mean if v is not None else None for a, v in anchor.items()}
        targets["session_relative_momentum"].append(positive_weights(relative, policy))
        targets["session_momentum_ablation"].append(positive_weights(anchor, policy))
        targets["eligible_equal_weight"].append(
            positive_weights(eligible, policy, equal_weight=True)
        )
        targets["cash"].append({})
    if experiment in ("low_turnover_opening", "activity_reversal"):
        for name, original in OPENING_ARMS.items():
            # No additional factor: identical causal signal at the one frozen clock.
            targets[name] = [
                dict(value) if i == 3 else {} for i, value in enumerate(targets[original])
            ]
    elif experiment != "sleeve_baseline":
        raise ValueError("unsupported economic experiment")
    return targets


def _correlations(daily: list[dict[str, Any]], names: list[str]) -> dict[str, float | None]:
    # Daily zero-cost strategy-return correlation is a behavioral diagnostic;
    # it does not prune the frozen candidate denominator.
    result: dict[str, float | None] = {}
    for i, left in enumerate(names):
        for right in names[i + 1 :]:
            pairs = [(d["results"][left]["0.0"], d["results"][right]["0.0"]) for d in daily]
            if any(not a["resolved"] or not b["resolved"] for a, b in pairs) or len(pairs) < 2:
                result[left + "/" + right] = None
                continue
            x = [a["net_return"] for a, _ in pairs]
            y = [b["net_return"] for _, b in pairs]
            mx, my = math.fsum(x) / len(x), math.fsum(y) / len(y)
            xx, yy = [v - mx for v in x], [v - my for v in y]
            scale = math.sqrt(math.fsum(v * v for v in xx) * math.fsum(v * v for v in yy))
            result[left + "/" + right] = (
                math.fsum(a * b for a, b in zip(xx, yy, strict=True)) / scale if scale > 0 else None
            )
    return result


def run_campaign(
    protocol_path: Path, output_root: Path, *, progress: Progress | None = None
) -> dict[str, Any]:
    protocol = _sealed(protocol_path, "protocol_id", "us-r3-economic-protocol-")
    if protocol["implementation_id"] != code_identity():
        raise ValueError("implementation changed; freeze a new protocol before evaluating")
    for binding in protocol["inputs"].values():
        if file_digest(Path(binding["path"])) != binding["sha256"]:
            raise ValueError("bound input changed")
    write_immutable_json(output_root / "protocol.json", protocol)
    policy = EconomicPolicy(
        **{**protocol["policy"], "cost_bps": tuple(protocol["policy"]["cost_bps"])}
    )
    expected = protocol["sessions"]

    def compact(payload: dict[str, Any]) -> dict[str, Any]:
        # One session's full trade ledger lives in memory at a time.
        for grid in payload["results"].values():
            for result in grid.values():
                result.pop("ledger", None)
        return payload

    daily: dict[str, dict[str, Any]] = {}
    for day in expected:
        path = output_root / "sessions" / (day + ".json")
        if path.exists():
            saved = _sealed(path, "evidence_id", "us-r3-economic-session-")
            if saved["protocol_id"] != protocol["protocol_id"] or saved["session_date"] != day:
                raise ValueError("session binding mismatch")
            daily[day] = compact(saved)
    resumed = len(daily)
    calendar = {
        s.session_date.isoformat(): s
        for s in _calendar(Path(protocol["inputs"]["calendar"]["path"])).sessions
    }
    source = Path(protocol["inputs"]["source"]["path"])

    def evaluate(
        day: str,
        source_assets: tuple[FactorPanelAsset, ...],
        marks: ExecutionMarks,
        activity: dict[str, list[float | None]] | None = None,
    ) -> None:
        assets = aligned_session(source_assets, calendar[day], protocol["universe"])
        results: dict[str, dict[str, Any]]
        if not source_assets:
            results = {
                name: {
                    str(float(cost)): {
                        "resolved": False,
                        "net_return": None,
                        "reason": "MISSING_SESSION",
                        "canceled_entries": 0,
                        "ledger": [],
                    }
                    for cost in policy.cost_bps
                }
                for name in protocol["strategies"]
            }
        else:
            targets = session_targets(assets, policy, protocol["experiment"])
            if protocol["experiment"] == "activity_reversal":
                if activity is None:
                    raise ValueError("activity history is required")
                targets.update(activity_targets(assets, activity, policy))
            reference_minutes = 5 if policy.execution_profile == "pending_exit_5m" else 15
            clocks = [
                calendar[day].open_at + timedelta(minutes=reference_minutes * (i + 1))
                for i in range(calendar[day].regular_minutes // reference_minutes)
            ]
            allowed = {(a.asset_id, clock) for a in assets for clock in clocks}
            if not set(marks) <= allowed:
                raise ValueError("execution marks outside frozen universe/calendar")
            prices = [
                {a.asset_id: marks.get((a.asset_id, clock)) for a in assets} for clock in clocks
            ]
            results = {
                name: {
                    str(float(cost)): simulate_session(
                        prices,
                        targets[name],
                        policy,
                        cost_bps=cost,
                        schedule=protocol["allocation_schedules"][name],
                    )
                    for cost in policy.cost_bps
                }
                for name in protocol["strategies"]
            }
        payload = {
            "schema_version": "finagent.us-r3-economic-session.v2",
            "protocol_id": protocol["protocol_id"],
            "session_date": day,
            "results": results,
            "activity_ratios": activity,
            "execution_reference_coverage": {
                asset: {
                    "expected": calendar[day].regular_minutes
                    // (5 if policy.execution_profile == "pending_exit_5m" else 15),
                    "observed": sum(
                        price is not None for (name, _), price in marks.items() if name == asset
                    ),
                    "explicit_missing": sum(
                        price is None for (name, _), price in marks.items() if name == asset
                    ),
                }
                for asset in protocol["universe"]
            },
            **AUTHORITY,
        }
        payload["evidence_id"] = "us-r3-economic-session-" + digest(payload)
        write_immutable_json(output_root / "sessions" / (day + ".json"), payload)
        daily[day] = compact(payload)
        if progress:
            progress(
                "session_complete",
                {"session_date": day, "completed": len(daily), "total": len(expected)},
            )

    if len(daily) < len(expected) and protocol["experiment"] == "activity_reversal":
        history = ActivityHistory()
        # Rebuild causal state on partial resume, including already evaluated
        # days and missing calendar sessions. Warm-up never evaluates returns.
        with closing(
            iter_feature_sessions(Path(protocol["inputs"]["history_source"]["path"]))
        ) as rows:
            frame = next(rows, None)
            for day in protocol["activity_experiment"]["warmup_sessions"]:
                while frame is not None and frame[0] < day:
                    frame = next(rows, None)
                raw = frame[1] if frame is not None and frame[0] == day else ()
                history.process(
                    date.fromisoformat(day),
                    aligned_session(raw, calendar[day], protocol["universe"]),
                )
        with (
            closing(iter_feature_sessions(source)) as features,
            closing(iter_execution_sessions(source, policy.execution_profile)) as executions,
        ):
            frame = next(features, None)
            reference = next(executions, None)
            for day in expected:
                while frame is not None and frame[0] < day:
                    frame = next(features, None)
                while reference is not None and reference[0] < day:
                    reference = next(executions, None)
                has_features = frame is not None and frame[0] == day
                has_marks = reference is not None and reference[0] == day
                if has_features != has_marks:
                    raise ValueError("feature/execution session mismatch")
                raw = frame[1] if frame is not None and has_features else ()
                ratios = history.process(
                    date.fromisoformat(day),
                    aligned_session(raw, calendar[day], protocol["universe"]),
                )
                if day not in daily:
                    evaluate(
                        day,
                        raw,
                        reference[1] if reference is not None and has_marks else {},
                        ratios,
                    )
    elif len(daily) < len(expected):
        seen: set[str] = set()
        # Two explicit projections keep execution prices out of feature inputs.
        # Both are bounded to one session; close handles even after interruption.
        with (
            closing(iter_feature_sessions(source)) as features,
            closing(iter_execution_sessions(source, policy.execution_profile)) as executions,
        ):
            for day, assets, _ in features:
                if day in seen:
                    raise ValueError("duplicate source session")
                seen.add(day)
                reference = next(executions, None)
                if reference is None or reference[0] != day:
                    raise ValueError("feature/execution session mismatch")
                if day in expected and day not in daily:
                    evaluate(day, assets, reference[1])
            if next(executions, None) is not None:
                raise ValueError("extra execution session")
        for day in expected:
            if day not in daily:
                evaluate(day, (), {})
    for binding in protocol["inputs"].values():
        if file_digest(Path(binding["path"])) != binding["sha256"]:
            raise ValueError("bound input mutated during evaluation")
    ordered = [daily[day] for day in expected]
    # Drop bulky ledgers before aggregation; immutable per-session files retain them.
    summary = {
        name: {
            str(float(cost)): summarize_sessions(
                [d["results"][name][str(float(cost))] for d in ordered]
            )
            for cost in policy.cost_bps
        }
        for name in protocol["strategies"]
    }
    comparisons: dict[str, Any] = {}
    comparison_controls = {}
    if protocol["experiment"] in ("low_turnover_opening", "activity_reversal"):
        comparison_controls = {
            name: ("opening_60m_equal_weight", "cash", OPENING_ARMS[name])
            for name in ("opening_60m_momentum", "opening_60m_relative_momentum")
        }
    if protocol["experiment"] == "activity_reversal":
        comparison_controls[ACTIVITY_ARMS[0]] = (ACTIVITY_ARMS[1], ACTIVITY_ARMS[2], "cash")
    if comparison_controls:
        for name, controls in comparison_controls.items():
            comparisons[name] = {}
            for control in controls:
                comparisons[name][control] = {}
                for cost in policy.cost_bps:
                    key = str(float(cost))
                    pairs = [(d["results"][name][key], d["results"][control][key]) for d in ordered]
                    complete = all(a["resolved"] and b["resolved"] for a, b in pairs)
                    comparisons[name][control][key] = {
                        "scheduled_sessions": len(pairs),
                        "full_period_evaluable": complete,
                        "mean_daily_excess_bps": math.fsum(
                            a["net_return"] - b["net_return"] for a, b in pairs
                        )
                        / len(pairs)
                        * 10000
                        if complete
                        else None,
                        "compounded_return_difference": cast(
                            float, summary[name][key]["compounded_return"]
                        )
                        - cast(float, summary[control][key]["compounded_return"])
                        if complete
                        else None,
                        "scope": "paired descriptive comparison; not a tradable spread or risk-adjusted Alpha",
                    }
    report = {
        "schema_version": "finagent.us-r3-economic-screen.v2",
        "protocol_id": protocol["protocol_id"],
        "session_evidence_ids": [d["evidence_id"] for d in ordered],
        "summary": summary,
        "opening_paired_comparisons": comparisons,
        "execution_reference_coverage": {
            asset: {
                field: sum(d["execution_reference_coverage"][asset][field] for d in ordered)
                for field in ("expected", "observed", "explicit_missing")
            }
            for asset in protocol["universe"]
        },
        "zero_cost_daily_return_correlations": _correlations(ordered, protocol["strategies"]),
        "terminal": "EXPLORATORY_COMPLETE"
        if all(s["full_period_evaluable"] for grid in summary.values() for s in grid.values())
        else "EXPLORATORY_INCOMPLETE_EVIDENCE",
        "selection_applied": False,
        **AUTHORITY,
    }
    report["evidence_id"] = "us-r3-economic-screen-" + digest(report)
    write_immutable_json(output_root / "summary.json", report)
    return {**report, "resumed_sessions": resumed, "evaluated_sessions": len(expected) - resumed}
