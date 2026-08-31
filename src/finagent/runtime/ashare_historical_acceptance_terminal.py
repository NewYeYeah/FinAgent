from __future__ import annotations

import hashlib
import json
import zipfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

from finagent.backtest import StrategyDecisionSeriesProjection
from finagent.data import LocalAshareDatasetLayout, LocalAshareFrozenManifest
from finagent.research import FactorSeriesProjection
from finagent.visualization.workbench_api import create_workspace_app

from .ashare_historical_acceptance import (
    AC3_ACCEPTANCE_ID_PREFIX,
    AC3_ACCEPTANCE_SCHEMA,
    AC3_EVIDENCE_METHODS,
    AC3_REQUIRED_COMMANDS,
    AshareHistoricalAcceptanceConfig,
    AshareHistoricalAcceptanceResult,
    AshareHistoricalAcceptanceRunner,
)

_NO_ALPHA_SELECTION_STATUS = "NO_ROBUST_FACTOR_FOUND"
_NO_ALPHA_A4_STATUS = "NO_ROBUST_FACTOR_FAMILY"
_NO_ALPHA_REASON_CODES = {
    "NO_A2P6_FACTOR_PASSED_PREREGISTERED_GATE",
    "NO_PORTFOLIO_BACKTEST_EXECUTED",
    "RESERVE_UNTOUCHED",
}


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be a mapping")
    return cast(Mapping[str, Any], value)


def _sequence(value: object) -> Sequence[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return cast(Sequence[Any], value)
    return ()


def _load_json(path: Path, name: str) -> Mapping[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return _mapping(raw, name)


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=str,
    )


def _digest(prefix: str, value: object, length: int = 40) -> str:
    digest = hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()
    return f"{prefix}-{digest[:length]}"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise FileNotFoundError(path)
    return {
        "path": str(path),
        "sha256": _sha256(path),
        "size_bytes": path.stat().st_size,
    }


def _resolve(root: Path, value: object) -> Path:
    path = Path(str(value)).expanduser()
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _report_path(record: Any) -> Path:
    outputs = record.outputs or {}
    value = outputs.get("report_path")
    if not value:
        raise ValueError(f"CommandRun {record.run.command_run_id} has no report_path")
    return Path(str(value)).expanduser().resolve()


def _command_records(runner: AshareHistoricalAcceptanceRunner) -> dict[str, object]:
    records = runner.store.list(limit=500)
    output: dict[str, object] = {}
    for command_id in AC3_REQUIRED_COMMANDS:
        matches = tuple(record for record in records if record.run.command_id == command_id)
        if len(matches) != 1:
            output[command_id] = {
                "ok": False,
                "reason": f"expected one CommandRun, found {len(matches)}",
            }
            continue
        record = matches[0]
        output[command_id] = {
            "ok": record.run.state == "succeeded" and record.result is not None,
            "command_run_id": record.run.command_run_id,
            "state": record.run.state,
            "config_snapshot_id": record.intent.config_snapshot_id,
            "evidence_ids": list(record.result.evidence_ids if record.result else ()),
            "artifact_paths": list(record.artifact_paths),
            "outputs": dict(record.outputs or {}),
        }
    return output


def _command_ok(records: Mapping[str, object], command_id: str) -> bool:
    value = records.get(command_id)
    return isinstance(value, Mapping) and value.get("ok") is True


def is_no_alpha_terminal(
    robust: Mapping[str, object],
    a4: Mapping[str, object],
) -> bool:
    selection = _mapping(robust.get("frozen_selection"), "frozen_selection")
    outcome = _mapping(a4.get("research_outcome"), "research_outcome")
    return (
        str(selection.get("status", "")) == _NO_ALPHA_SELECTION_STATUS
        and not tuple(_sequence(selection.get("components")))
        and str(outcome.get("status", "")) == _NO_ALPHA_A4_STATUS
        and outcome.get("execution_validation_passed") is False
        and outcome.get("promotion_eligible") is False
        and _NO_ALPHA_REASON_CODES
        <= {str(value) for value in _sequence(outcome.get("reason_codes"))}
    )


def _complete_no_alpha_terminal(
    runner: AshareHistoricalAcceptanceRunner,
) -> AshareHistoricalAcceptanceResult:
    development = runner._audited_command(  # noqa: SLF001 - same-package recovery path
        "research.run_development",
        snapshot=runner.development_snapshot,
    )
    robust_record = runner._audited_command(  # noqa: SLF001
        "research.run_a2p6",
        snapshot=runner.robust_snapshot,
    )
    a4_record = runner._audited_command(  # noqa: SLF001
        "portfolio.run_a4",
        snapshot=runner.portfolio_snapshot,
    )
    development_report = _report_path(development)
    robust_report = _report_path(robust_record)
    a4_report = _report_path(a4_record)
    development_payload = _load_json(development_report, "development report")
    robust = _load_json(robust_report, "A2.6 report")
    a4 = _load_json(a4_report, "A4 report")
    if not is_no_alpha_terminal(robust, a4):
        raise RuntimeError(
            "StrategyDecisionSeries is empty but A2.6/A4 do not form the reviewed "
            "NO_ROBUST_FACTOR_FOUND → NO_ROBUST_FACTOR_FAMILY terminal path"
        )

    validation_id = str(a4.get("portfolio_validation_id", "")).strip()
    robust_result_id = str(robust.get("program_result_id", "")).strip()
    data_version = str(robust.get("data_version", "")).strip()
    development_id = str(development_payload.get("acceptance_id", "")).strip()
    if not validation_id or not robust_result_id or not data_version or not development_id:
        raise ValueError("A-C3 no-alpha terminal is missing required evidence identities")

    factor_manifest_path = robust_report.with_name(
        f"{robust_report.stem}.factor-series.json"
    )
    strategy_manifest_path = a4_report.with_name(
        f"{a4_report.stem}.strategy-decisions.json"
    )
    strategy = StrategyDecisionSeriesProjection(strategy_manifest_path)
    factors = FactorSeriesProjection(factor_manifest_path)
    strategy_manifest = strategy.manifest
    factor_manifest = factors.manifest

    ledger_path = _resolve(
        runner.config.repository_root,
        runner.portfolio_values.get("ledger_path", "reports/ashare_a4_ledger.jsonl"),
    )
    if not ledger_path.is_file():
        raise FileNotFoundError(ledger_path)

    frozen = LocalAshareFrozenManifest.read_json(runner.frozen_manifest)
    if not frozen.content_hashed:
        raise ValueError(
            "A-C3 real no-alpha acceptance requires content_hashed=true frozen manifest"
        )
    frozen.verify(LocalAshareDatasetLayout(runner.dataset_root), verify_content=True)
    dataset_attested = frozen.dataset_version == data_version

    evidence_roots = tuple(
        sorted(
            {development_report.parent, robust_report.parent, a4_report.parent},
            key=lambda path: path.as_posix(),
        )
    )
    review_bundle = runner.state_dir / f"finagent-review-{validation_id}.zip"
    runner._audited_command(  # noqa: SLF001
        "review.export_bundle",
        parameters={
            "validation_id": validation_id,
            "reports": tuple(str(path) for path in evidence_roots),
            "output": str(review_bundle),
            "git_sha": runner.config.git_sha,
        },
        context={"portfolio_validation_id": validation_id},
    )

    command_records = _command_records(runner)
    app = create_workspace_app(
        report_paths=evidence_roots,
        config_paths=(),
        command_store_path=runner.command_store_path,
        frontend_dir=None,
        git_sha=runner.config.git_sha,
    )
    strategy_item = app.state.strategy_explorer.by_portfolio(validation_id)
    dimensions = app.state.strategy_explorer.dimensions(strategy_item.series_id)
    portfolio = app.state.workspace_v2.portfolio_cockpit(validation_id)
    portfolio_catalog = app.state.portfolio_execution.catalog()
    linked = app.state.linked_analytics_acceptance.status()

    v4_methods_ok = True
    v4_route_methods: dict[str, list[str]] = {}
    for route in app.routes:
        route_path = str(getattr(route, "path", ""))
        if not route_path.startswith("/api/v4/"):
            continue
        methods = set(getattr(route, "methods", set()) or set())
        v4_route_methods[route_path] = sorted(methods)
        if not methods <= AC3_EVIDENCE_METHODS:
            v4_methods_ok = False

    robust_reserve = _mapping(robust.get("reserve"), "robust reserve")
    a4_reserve = _mapping(a4.get("reserve"), "A4 reserve")
    a4_spec = _mapping(a4.get("validation_spec"), "validation_spec")
    a4_outcome = _mapping(a4.get("research_outcome"), "research_outcome")
    development_reserve = _mapping(
        development_payload.get("reserve"),
        "development reserve",
    )
    portfolio_items = tuple(_sequence(portfolio_catalog.get("items")))
    market_manifest_path = strategy_manifest_path.with_name(
        f"{strategy_manifest_path.name.removesuffix('.json')}.market-bars.json"
    )

    checks: dict[str, bool] = {
        "git_sha_recorded": bool(runner.config.git_sha.strip()),
        "dataset_content_hashed": frozen.content_hashed,
        "dataset_content_verified": dataset_attested,
        "development_passed": development_payload.get("passed") is True,
        "development_reserve_untouched": (
            str(development_reserve.get("status", "")) == "untouched"
        ),
        "development_data_version_matches": (
            str(development_payload.get("data_version", "")) == data_version
        ),
        "robust_program_frozen": str(robust.get("program_status", "")) == "frozen",
        "robust_reserve_untouched": str(robust_reserve.get("status", "")) == "untouched",
        "no_alpha_terminal_exact": is_no_alpha_terminal(robust, a4),
        "a4_reserve_untouched": str(a4_reserve.get("status", "")) == "untouched",
        "a4_binds_robust_program": (
            str(a4_spec.get("source_program_result_id", "")) == robust_result_id
        ),
        "a4_data_version_matches": str(a4_spec.get("data_version", "")) == data_version,
        "a4_has_no_folds": not tuple(_sequence(a4.get("folds"))),
        "a4_has_no_aggregate": a4.get("aggregate") is None,
        "a4_no_execution": a4_outcome.get("execution_validation_passed") is False,
        "a4_no_promotion": a4_outcome.get("promotion_eligible") is False,
        "a4_ledger_empty": ledger_path.stat().st_size == 0,
        "strategy_empty_is_explicit": (
            strategy_manifest.row_count == 0
            and strategy_manifest.row_session_count == 0
            and strategy_manifest.asset_count == 0
            and strategy_manifest.start_date is None
            and strategy_manifest.end_date is None
        ),
        "strategy_binds_a4": strategy_manifest.portfolio_validation_id == validation_id,
        "strategy_binds_robust": (
            strategy_manifest.source_program_result_id == robust_result_id
        ),
        "strategy_data_version_matches": strategy_manifest.data_version == data_version,
        "factor_series_verified": factor_manifest.row_count > 0,
        "factor_binds_robust": factor_manifest.program_result_id == robust_result_id,
        "factor_data_version_matches": factor_manifest.data_version == data_version,
        "market_bars_explicitly_absent": not market_manifest_path.exists(),
        "workbench_strategy_identity_exact": (
            strategy_item.series_id == strategy_manifest.series_id
        ),
        "workbench_strategy_dimensions_empty": (
            not tuple(_sequence(dimensions.get("assets")))
            and int(dimensions.get("session_count", 0)) == 0
        ),
        "workbench_no_portfolio_explicit": portfolio.get("no_portfolio") is True,
        "workbench_portfolio_execution_omits_unavailable": all(
            not isinstance(item, Mapping)
            or str(item.get("portfolio_validation_id", "")) != validation_id
            for item in portfolio_items
        ),
        "linked_analytics_accepted": linked.get("accepted") is True,
        "linked_no_browser_recompute": linked.get("browser_recomputation") is False,
        "linked_missing_policy_explicit": (
            linked.get("missing_evidence_policy") == "explicit_unavailable_not_inferred"
        ),
        "evidence_plane_v4_get_only": v4_methods_ok,
        "command_runs_complete": all(
            _command_ok(command_records, command) for command in AC3_REQUIRED_COMMANDS
        ),
        "review_bundle_valid_zip": (
            zipfile.is_zipfile(review_bundle) and review_bundle.stat().st_size > 0
        ),
    }
    contract_valid = all(checks.values())
    accepted = contract_valid and dataset_attested
    acceptance_id = _digest(
        AC3_ACCEPTANCE_ID_PREFIX,
        {
            "terminal_state": _NO_ALPHA_A4_STATUS,
            "git_sha": runner.config.git_sha,
            "data_version": data_version,
            "development_acceptance_id": development_id,
            "program_result_id": robust_result_id,
            "portfolio_validation_id": validation_id,
            "strategy_series_id": strategy_manifest.series_id,
            "factor_series_id": factor_manifest.series_id,
            "review_bundle_sha256": _sha256(review_bundle),
            "checks": checks,
        },
    )
    payload: dict[str, object] = {
        "schema_version": AC3_ACCEPTANCE_SCHEMA,
        "acceptance_id": acceptance_id,
        "stage": "A-C3",
        "mode": "real_local_dataset",
        "terminal_state": _NO_ALPHA_A4_STATUS,
        "contract_valid": contract_valid,
        "accepted": accepted,
        "real_dataset_attested": dataset_attested,
        "acceptance_semantics": (
            "NO_ROBUST_FACTOR_FOUND is a valid research terminal state. A-C3 accepts "
            "it only when A4 explicitly records NO_ROBUST_FACTOR_FAMILY, no portfolio "
            "backtest was executed, StrategyDecisionSeries is empty, MarketBarSeries "
            "is not inferred, the reserve is untouched, and Workbench unavailability "
            "is explicit."
        ),
        "git_sha": runner.config.git_sha,
        "data": {
            "root": str(runner.dataset_root),
            "frozen_manifest": str(runner.frozen_manifest),
            "dataset_version": frozen.dataset_version,
            "content_hashed": frozen.content_hashed,
            "content_verified": True,
        },
        "identities": {
            "development_acceptance_id": development_id,
            "program_result_id": robust_result_id,
            "portfolio_validation_id": validation_id,
            "strategy_series_id": strategy_manifest.series_id,
            "factor_series_id": factor_manifest.series_id,
            "market_bar_series_id": None,
            "data_version": data_version,
        },
        "checks": checks,
        "command_runs": command_records,
        "evidence_plane": {
            "read_only": True,
            "v4_route_methods": v4_route_methods,
            "linked_analytics": linked,
        },
        "artifacts": {
            "development": _artifact(development_report),
            "robust": _artifact(robust_report),
            "a4": _artifact(a4_report),
            "a4_ledger": _artifact(ledger_path),
            "factor_manifest": _artifact(factor_manifest_path),
            "strategy_manifest": _artifact(strategy_manifest_path),
            "market_bar_manifest": None,
            "review_bundle": _artifact(review_bundle),
            "command_store": _artifact(runner.command_store_path),
        },
    }
    target = runner.config.acceptance_report
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return AshareHistoricalAcceptanceResult(payload=payload, report_path=target)


def run_ashare_historical_acceptance(
    config: AshareHistoricalAcceptanceConfig,
    *,
    confirmed: bool,
) -> AshareHistoricalAcceptanceResult:
    runner = AshareHistoricalAcceptanceRunner(config, confirmed=confirmed)
    try:
        return runner.run()
    except RuntimeError as exc:
        if "StrategyDecisionSeries has no date range" not in str(exc):
            raise
        return _complete_no_alpha_terminal(runner)
