from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from datetime import datetime
from pathlib import Path

from finagent.data.minute_store import (
    DuckDBExecutionPolicy,
    DuckDBParquetMinuteStore,
    manifest_from_huggingface_snapshot,
)
from finagent.data.minute_transform import load_trading_calendar_evidence_json
from finagent.research.replay_experiment_campaign import (
    ReplayCampaignSourceScope,
    ReplayExperimentCampaignSpec,
    run_replay_experiment_campaign,
    write_replay_experiment_campaign_report,
)
from finagent.research.us_agent_value_evaluation import USAgentValueEvaluationDenominator
from finagent.research.us_agent_value_gate import USAgentValueGateDecision
from finagent.research.us_agent_value_protocol import (
    USAgentValueArm,
    USAgentValuePhase,
    canonical_us_a0_experiment_protocol,
    canonical_us_a0_manual_candidates,
)
from finagent.research.us_baseline_evaluation import USBaselineRunSpec
from finagent.research.us_baselines import USBaselineProtocol, canonical_us_baseline_denominator
from finagent.research.us_r1_protocol import (
    USR1AgentScope,
    USR1CandidateDenominator,
    USR1CandidateProvenance,
    canonical_us_r1_research_protocol,
)

SOURCE_REVISION = "776328445b7ac6e7815ef3a483e9c8ded1eb6d56"
INVENTORY_ID = "us-minute-inventory-c2cbf682b456f97eb613ed65"
CLEANING_ID = "us-minute-cleaning-stack-a0d745a4a75d25a63e3a8244"
CALENDAR_ID = "trading-calendar-03a9c29f566d6634aedbbbdc"


def _symbols(raw: str) -> tuple[str, ...]:
    values = tuple(sorted(item.strip().upper() for item in raw.split(",") if item.strip()))
    if len(values) < 2:
        raise argparse.ArgumentTypeError("--symbols requires at least two comma-separated symbols")
    if len(values) != len(set(values)):
        raise argparse.ArgumentTypeError("--symbols cannot contain duplicates")
    return values


def _datetime(raw: str) -> datetime:
    try:
        value = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid ISO datetime: {raw}") from exc
    if value.tzinfo is None or value.utcoffset() is None:
        raise argparse.ArgumentTypeError("campaign datetimes must include an explicit UTC offset")
    return value


def _engineering_universe_id(symbols: tuple[str, ...]) -> str:
    digest = hashlib.sha256("\n".join(symbols).encode("utf-8")).hexdigest()[:24]
    return f"engineering-replay-campaign-universe-{digest}"


def _b0_run_spec(symbols: tuple[str, ...]) -> USBaselineRunSpec:
    return USBaselineRunSpec(
        certification_report_id="engineering-replay-parity-not-us-d3",
        certification_outcome="CERTIFIED_FOR_RESEARCH_UNDER_LIMITATIONS",
        engineering_universe_id=_engineering_universe_id(symbols),
        denominator_id=canonical_us_baseline_denominator().denominator_id,
        minimum_cross_section=2,
        minimum_evaluated_periods=1,
        minimum_ic_periods=1,
    )


def _a0_denominator() -> USAgentValueEvaluationDenominator:
    protocol = canonical_us_a0_experiment_protocol(USAgentValuePhase.PILOT)
    candidate = canonical_us_a0_manual_candidates()[8]
    return USAgentValueEvaluationDenominator(
        protocol_id=protocol.protocol_id,
        generation_run_id="engineering-replay-campaign-a0",
        generation_run_spec_id="engineering-replay-campaign-a0-spec",
        arm=USAgentValueArm.MANUAL,
        candidate_ids=(candidate.candidate_id,),
        protocol=USBaselineProtocol(),
        candidates=(candidate.compile_feature_spec(),),
    )


def _r1_denominator() -> USR1CandidateDenominator:
    candidate = canonical_us_a0_manual_candidates()[0]
    return USR1CandidateDenominator(
        protocol_id=canonical_us_r1_research_protocol().protocol_id,
        a0_phase=USAgentValuePhase.PILOT,
        a0_experiment_id="engineering-replay-campaign-a0",
        a0_gate_review_id="engineering-replay-campaign-no-gate-review",
        a0_gate_decision=USAgentValueGateDecision.PILOT_DO_NOT_PROCEED_TO_FORMAL,
        agent_scope=USR1AgentScope.CONTRACTED,
        candidates=(
            USR1CandidateProvenance(
                candidate=candidate,
                source_arms=(USAgentValueArm.MANUAL,),
                source_run_ids=("engineering-replay-campaign-a0-run",),
            ),
        ),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run an engineering-only streaming-vs-batch parity campaign over the frozen local "
            "U.S. minute snapshot. This command does not invoke the formal US-B0 operator, does "
            "not consume US-D3 certification authority and cannot advance docs/status.toml."
        )
    )
    parser.add_argument("root", type=Path, help="Local Hugging Face OHLCV-1m snapshot root")
    parser.add_argument("--symbols", type=_symbols, required=True)
    parser.add_argument("--start", type=_datetime, required=True, help="ISO datetime with offset")
    parser.add_argument("--end", type=_datetime, required=True, help="ISO datetime with offset")
    parser.add_argument(
        "--calendar",
        type=Path,
        default=Path("reports/us_calendar/xnys_1992_2026.json"),
    )
    parser.add_argument(
        "--report-output",
        type=Path,
        default=Path("reports/replay_experiment_campaign/replay_experiment_campaign.json"),
    )
    parser.add_argument("--maximum-batch-rows", type=int, default=100_000)
    parser.add_argument("--memory-limit", default="512MB")
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--max-temp-directory-size", default="4GB")
    parser.add_argument(
        "--temp-directory",
        type=Path,
        default=Path("data/duckdb_temp/replay_experiment_campaign"),
    )
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    symbols: tuple[str, ...] = args.symbols
    if args.end <= args.start:
        raise SystemExit("--end must be later than --start")

    manifest = manifest_from_huggingface_snapshot(
        args.root,
        expected_revision=SOURCE_REVISION,
        expected_inventory_id=INVENTORY_ID,
        cleaning_identity=CLEANING_ID,
    )
    store = DuckDBParquetMinuteStore(manifest)
    calendar = load_trading_calendar_evidence_json(
        args.calendar,
        expected_calendar_id=CALENDAR_ID,
    )
    execution_policy = DuckDBExecutionPolicy(
        memory_limit=args.memory_limit,
        threads=args.threads,
        allow_temp_spill=True,
        max_temp_directory_size=args.max_temp_directory_size,
        preserve_insertion_order=False,
    )
    spec = ReplayExperimentCampaignSpec(
        source_scope=ReplayCampaignSourceScope.LOCAL_BOUNDED,
        required_symbols=symbols,
        event_start=args.start,
        event_end=args.end,
        maximum_batch_rows=args.maximum_batch_rows,
    )
    report = asyncio.run(
        run_replay_experiment_campaign(
            store,
            calendar,
            spec=spec,
            b0_run_spec=_b0_run_spec(symbols),
            a0_denominator=_a0_denominator(),
            r1_denominator=_r1_denominator(),
            execution_policy=execution_policy,
            temp_directory=args.temp_directory,
        )
    )
    output = write_replay_experiment_campaign_report(
        report,
        args.report_output,
        overwrite=args.overwrite,
    )
    print(
        json.dumps(
            {
                "report_id": report.report_id,
                "passed": report.passed,
                "blockers": list(report.blockers),
                "spec_id": report.spec.spec_id,
                "source_scope": report.spec.source_scope.value,
                "source_manifest_id": report.source_manifest_id,
                "source_run_report_id": report.source_run_report_id,
                "streaming_bundle_id": report.streaming_bundle_id,
                "parity_check_count": len(report.parity_checks),
                "all_parity_equal": all(item.equal for item in report.parity_checks),
                "report_output": str(output),
                "formal_us_b0_operator_invoked": False,
                "us_d3_certification_consumed": False,
                "certification_authority": False,
                "research_authority": False,
                "agent_value_gate_authority": False,
                "alpha_authority": False,
                "execution_authority": False,
                "stage_exit_authority": False,
            },
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0 if report.passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
