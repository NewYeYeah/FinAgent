from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from finagent.data.us_instruments import materialize_engineering_universe_from_mt5_probe

DEFAULT_SOURCE_CANDIDATE = "hf-mito0o852-ohlcv-1m"
DEFAULT_SOURCE_REVISION = "776328445b7ac6e7815ef3a483e9c8ded1eb6d56"


def _mapping_pair(value: str) -> tuple[str, str]:
    research, separator, broker = value.partition("=")
    research = research.strip()
    broker = broker.strip()
    if not separator or not research or not broker:
        raise argparse.ArgumentTypeError(
            "mapping must use RESEARCH_SYMBOL=BROKER_SYMBOL, e.g. MSFT=MSFT"
        )
    return research, broker


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Materialize US-I0 ResearchInstrument ↔ BrokerInstrument mapping evidence "
            "from an accepted read-only MT5-P0 probe. Broker path metadata is retained "
            "but never treated as listed-exchange authority."
        )
    )
    parser.add_argument(
        "--mt5-probe",
        type=Path,
        required=True,
        help="Accepted MT5-P0 capability probe JSON",
    )
    parser.add_argument(
        "--mapping",
        type=_mapping_pair,
        action="append",
        default=[],
        help=(
            "Explicit research-to-broker symbol pair RESEARCH=BROKER; repeatable. "
            "No prefix/suffix stripping or symbol normalization is performed."
        ),
    )
    parser.add_argument(
        "--accept-for-engineering",
        action="append",
        default=[],
        help=(
            "Explicit operator attestation that the named research symbol maps to the "
            "broker symbol supplied by --mapping for engineering integration only. "
            "Repeat once per accepted research symbol."
        ),
    )
    parser.add_argument(
        "--source-candidate",
        default=DEFAULT_SOURCE_CANDIDATE,
        help="Research OHLCV source candidate identity",
    )
    parser.add_argument(
        "--source-revision",
        default=DEFAULT_SOURCE_REVISION,
        help="Immutable research OHLCV source revision",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/us_instruments/us_i0_engineering_universe.json"),
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if not args.mapping:
        raise SystemExit("at least one --mapping RESEARCH=BROKER pair is required")

    raw = json.loads(args.mt5_probe.read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping):
        raise SystemExit("MT5 probe JSON root must be an object")
    probe = cast(Mapping[str, object], raw)

    report = materialize_engineering_universe_from_mt5_probe(
        probe,
        mapping_pairs=tuple(args.mapping),
        accepted_research_symbols=frozenset(
            symbol.strip() for symbol in args.accept_for_engineering if symbol.strip()
        ),
        source_candidate=args.source_candidate,
        source_revision=args.source_revision,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report.to_dict(), sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    universe = report.universe
    summary = {
        "materialization_id": report.materialization_id,
        "accepted": report.accepted,
        "blockers": list(report.blockers),
        "limitations": list(report.limitations),
        "mt5_probe_id": report.mt5_probe_id,
        "broker_server": report.broker_server,
        "mapping_count": len(report.mappings),
        "accepted_mapping_count": sum(
            mapping.status.value == "accepted_for_engineering"
            for mapping in report.mappings
        ),
        "universe_id": universe.universe_id if universe is not None else None,
        "output": str(args.output),
    }
    print(json.dumps(summary, sort_keys=True, indent=2, ensure_ascii=False))
    return 0 if report.accepted else 2


if __name__ == "__main__":
    raise SystemExit(main())
