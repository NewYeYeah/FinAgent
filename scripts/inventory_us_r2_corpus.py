from __future__ import annotations

import argparse
import json
import tomllib
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from pathlib import Path

from finagent.data.minute_store import DuckDBExecutionPolicy, manifest_from_huggingface_snapshot
from finagent.domain.trading_calendar import TradingCalendarEvidence, TradingSession
from finagent.research.us_r2_inventory import (
    build_us_r2_corpus_inventory_plan,
    execute_us_r2_corpus_inventory,
)

SOURCE_REVISION = "776328445b7ac6e7815ef3a483e9c8ded1eb6d56"
INVENTORY_ID = "us-minute-inventory-c2cbf682b456f97eb613ed65"
CLEANING_ID = "us-minute-cleaning-stack-a0d745a4a75d25a63e3a8244"


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    return value


def _sequence(value: object, field_name: str) -> Sequence[object]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise TypeError(f"{field_name} must be a sequence")
    return value


def _text(value: object, field_name: str) -> str:
    rendered = str(value).strip() if value is not None else ""
    if not rendered:
        raise ValueError(f"{field_name} must be non-empty")
    return rendered


def _integer(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise TypeError(f"{field_name} must be integer-like")
    if isinstance(value, float) and not value.is_integer():
        raise ValueError(f"{field_name} must be integer-like")
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be integer-like") from exc


def _load_json(path: Path) -> Mapping[str, object]:
    payload: object = json.loads(path.read_text(encoding="utf-8"))
    return _mapping(payload, str(path))


def _load_status(path: Path) -> Mapping[str, object]:
    with path.open("rb") as handle:
        payload: object = tomllib.load(handle)
    return _mapping(payload, "status")


def _status_bindings(status: Mapping[str, object]) -> tuple[str, str, int, str]:
    if _text(status.get("current_stage"), "status.current_stage") != "US-R1":
        raise ValueError("US-R2-0 inventory requires the accepted US-R1 terminal as predecessor")
    if _text(status.get("next_stage"), "status.next_stage") != "research iteration":
        raise ValueError("US-R2-0 must start from the governed research-iteration branch")
    stages = _mapping(status.get("stage"), "status.stage")
    us_r1 = _mapping(stages.get("us_r1"), "status.stage.us_r1")
    if _text(us_r1.get("terminal"), "status.stage.us_r1.terminal") != "NO_ROBUST_FACTOR_FAMILY":
        raise ValueError("US-R2-0 is the negative-US-R1 research-iteration path")
    us_i0 = _mapping(stages.get("us_i0"), "status.stage.us_i0")
    us_c0 = _mapping(stages.get("us_c0"), "status.stage.us_c0")
    return (
        _text(
            us_i0.get("final_engineering_universe_id"),
            "status.stage.us_i0.final_engineering_universe_id",
        ),
        _text(
            us_r1.get("candidate_denominator_id"),
            "status.stage.us_r1.candidate_denominator_id",
        ),
        _integer(
            us_r1.get("candidate_denominator_count"),
            "status.stage.us_r1.candidate_denominator_count",
        ),
        _text(us_c0.get("calendar_id"), "status.stage.us_c0.calendar_id"),
    )


def _load_engineering_universe(path: Path) -> tuple[str, tuple[str, ...]]:
    document = _load_json(path)
    if document.get("accepted") is not True:
        raise ValueError("engineering-universe report must be accepted")
    universe_id = _text(document.get("universe_id"), "engineering_universe.universe_id")
    base = _mapping(document.get("base_finalization"), "engineering_universe.base_finalization")
    materialization = _mapping(base.get("materialization"), "engineering_universe.materialization")
    raw_mappings = _sequence(materialization.get("mappings"), "engineering_universe.mappings")
    assets: list[str] = []
    for index, raw in enumerate(raw_mappings):
        mapping = _mapping(raw, f"engineering_universe.mappings[{index}]")
        research = _mapping(
            mapping.get("research"), f"engineering_universe.mappings[{index}].research"
        )
        assets.append(
            _text(
                research.get("source_symbol"),
                f"engineering_universe.mappings[{index}].research.source_symbol",
            )
        )
    normalized = tuple(sorted(dict.fromkeys(assets)))
    if not normalized:
        raise ValueError("engineering-universe report contains no research symbols")
    return universe_id, normalized


def _load_candidate_denominator(path: Path) -> tuple[str, int]:
    document = _load_json(path)
    if document.get("performance_filter_applied") is not False:
        raise ValueError("R2 first replication requires performance_filter_applied=false")
    return (
        _text(document.get("denominator_id"), "candidate_denominator.denominator_id"),
        _integer(document.get("candidate_count"), "candidate_denominator.candidate_count"),
    )


def _parse_datetime(value: object, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(_text(value, field_name))
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO datetime") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return parsed


def _parse_optional_datetime(value: object, field_name: str) -> datetime | None:
    if value is None:
        return None
    return _parse_datetime(value, field_name)


def _load_calendar(path: Path) -> TradingCalendarEvidence:
    document = _load_json(path)
    evidence = _mapping(document.get("evidence"), "calendar.evidence")
    raw_sessions = _sequence(evidence.get("sessions"), "calendar.evidence.sessions")
    sessions: list[TradingSession] = []
    for index, raw in enumerate(raw_sessions):
        item = _mapping(raw, f"calendar.evidence.sessions[{index}]")
        sessions.append(
            TradingSession(
                session_date=date.fromisoformat(
                    _text(item.get("session_date"), f"calendar.sessions[{index}].session_date")
                ),
                open_at=_parse_datetime(
                    item.get("open_at"), f"calendar.sessions[{index}].open_at"
                ),
                close_at=_parse_datetime(
                    item.get("close_at"), f"calendar.sessions[{index}].close_at"
                ),
                pre_open_at=_parse_optional_datetime(
                    item.get("pre_open_at"), f"calendar.sessions[{index}].pre_open_at"
                ),
                post_close_at=_parse_optional_datetime(
                    item.get("post_close_at"), f"calendar.sessions[{index}].post_close_at"
                ),
                is_half_day=bool(item.get("is_half_day")),
            )
        )
    return TradingCalendarEvidence(
        market_id=_text(evidence.get("market_id"), "calendar.evidence.market_id"),
        timezone=_text(evidence.get("timezone"), "calendar.evidence.timezone"),
        source=_text(evidence.get("source"), "calendar.evidence.source"),
        source_revision=_text(evidence.get("source_revision"), "calendar.evidence.source_revision"),
        sessions=tuple(sessions),
        regular_session_minutes=_integer(
            evidence.get("regular_session_minutes"), "calendar.evidence.regular_session_minutes"
        ),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Inventory US-R2 historical regular-session coverage without evaluating any factor. "
            "The DuckDB scan is independent of the frozen 37-candidate denominator."
        )
    )
    parser.add_argument("root", type=Path, help="Local admitted OHLCV-1m snapshot root")
    parser.add_argument("--status", type=Path, default=Path("docs/status.toml"))
    parser.add_argument(
        "--universe-report",
        type=Path,
        default=Path("reports/us_instruments/us_i0_target_broker_final_engineering_universe.json"),
    )
    parser.add_argument(
        "--candidate-denominator-report",
        type=Path,
        default=Path("reports/us_r1/us_r1_candidate_denominator.json"),
    )
    parser.add_argument(
        "--calendar-report",
        type=Path,
        default=Path("reports/us_calendar/xnys_1992_2026.json"),
    )
    parser.add_argument("--memory-limit", default="512MB")
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument(
        "--allow-temp-spill", action=argparse.BooleanOptionalAction, default=True
    )
    parser.add_argument("--max-temp-directory-size", default="4GB")
    parser.add_argument(
        "--temp-directory", type=Path, default=Path("data/duckdb_temp/us_r2_0")
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/us_r2/us_r2_regime_corpus_inventory.json"),
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    status = _load_status(args.status)
    expected_universe_id, expected_denominator_id, expected_candidate_count, expected_calendar_id = (
        _status_bindings(status)
    )
    universe_id, assets = _load_engineering_universe(args.universe_report)
    denominator_id, candidate_count = _load_candidate_denominator(args.candidate_denominator_report)
    calendar = _load_calendar(args.calendar_report)

    if universe_id != expected_universe_id:
        raise SystemExit("engineering-universe report does not match docs/status.toml authority")
    if denominator_id != expected_denominator_id or candidate_count != expected_candidate_count:
        raise SystemExit("candidate denominator does not match docs/status.toml US-R1 authority")
    if calendar.calendar_id != expected_calendar_id:
        raise SystemExit("calendar report does not match docs/status.toml US-C0 authority")

    manifest = manifest_from_huggingface_snapshot(
        args.root,
        expected_revision=SOURCE_REVISION,
        expected_inventory_id=INVENTORY_ID,
        cleaning_identity=CLEANING_ID,
    )
    plan = build_us_r2_corpus_inventory_plan(manifest, calendar, assets)
    policy = DuckDBExecutionPolicy(
        memory_limit=args.memory_limit,
        threads=args.threads,
        allow_temp_spill=args.allow_temp_spill,
        max_temp_directory_size=args.max_temp_directory_size,
        preserve_insertion_order=False,
    )
    temp_directory = args.temp_directory if policy.allow_temp_spill else None
    corpus = execute_us_r2_corpus_inventory(
        plan,
        manifest,
        calendar,
        engineering_universe_id=universe_id,
        candidate_denominator_id=denominator_id,
        policy=policy,
        temp_directory=temp_directory,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(corpus.to_dict(), sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    console = {
        "corpus_id": corpus.corpus_id,
        "passed": corpus.passed,
        "blockers": list(corpus.blockers),
        "plan_id": plan.plan_id,
        "scan_strategy": plan.to_dict()["scan_strategy"],
        "asset_count": len(plan.assets),
        "candidate_count_bound_but_not_scanned": candidate_count,
        "partition_count": len(plan.partition_months),
        "selected_size_bytes": plan.selected_size_bytes,
        "common_all_asset_start": (
            corpus.common_all_asset_start.isoformat() if corpus.common_all_asset_start else None
        ),
        "common_all_asset_end": (
            corpus.common_all_asset_end.isoformat() if corpus.common_all_asset_end else None
        ),
        "common_all_asset_session_count": corpus.common_all_asset_session_count,
        "asset_history": [
            {
                "asset": item.asset,
                "first": item.first_observed_session.isoformat()
                if item.first_observed_session
                else None,
                "last": item.last_observed_session.isoformat()
                if item.last_observed_session
                else None,
                "active_span_session_coverage": (
                    None
                    if item.active_span_expected_session_count == 0
                    else item.active_span_observed_session_count
                    / item.active_span_expected_session_count
                ),
                "active_span_regular_minute_coverage": (
                    item.active_span_regular_minute_coverage_ratio
                ),
            }
            for item in corpus.asset_coverages
        ],
        "output": str(args.output),
    }
    print(json.dumps(console, sort_keys=True, indent=2, ensure_ascii=False))
    return 0 if corpus.passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
