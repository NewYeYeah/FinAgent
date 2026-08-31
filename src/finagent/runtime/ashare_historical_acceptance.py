from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tomllib
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from finagent.application import (
    HISTORICAL_APPLICATION_SERVICE_BINDINGS,
    ApplicationCommandInvocation,
    SQLiteCommandStore,
    historical_application_service_registry,
)
from finagent.backtest import StrategyDecisionSeriesProjection
from finagent.data import (
    AshareBarFrequency,
    LocalAshareDatasetLayout,
    LocalAshareFrozenManifest,
    MarketBarSeriesEvidence,
)
from finagent.research import FactorSeriesProjection
from finagent.visualization.historical_command_catalog import (
    default_historical_command_catalog,
)
from finagent.visualization.workbench_api import create_workspace_app
from finagent.visualization.workbench_control_catalog import ConfigRegistry, ConfigSnapshot

AC3_ACCEPTANCE_SCHEMA = "finagent.ashare-historical-e2e-acceptance.v1"
AC3_ACCEPTANCE_ID_PREFIX = "ashare-historical-ac3"
AC3_REQUIRED_COMMANDS = (
    "data.certify_local_ashare",
    "research.run_development",
    "research.run_a2p6",
    "portfolio.run_a4",
    "review.export_bundle",
)
AC3_EVIDENCE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

AshareHistoricalAcceptanceMode = Literal["real_local_dataset", "ci_contract_fixture"]


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be a mapping")
    return cast(Mapping[str, Any], value)


def _load_json(path: Path, name: str) -> Mapping[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return _mapping(raw, name)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
    value_digest = hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()
    return f"{prefix}-{value_digest[:length]}"


def _resolve(root: Path, value: object) -> Path:
    path = Path(str(value)).expanduser()
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _table(path: Path, section: str) -> dict[str, object]:
    with path.open("rb") as handle:
        raw = tomllib.load(handle)
    value = raw.get(section)
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain [{section}]")
    return {str(key): item for key, item in value.items()}


def _snapshot_for(
    registry: ConfigRegistry,
    *,
    section: str,
    source_path: Path,
) -> ConfigSnapshot:
    source_sha = _sha256(source_path)
    matches = tuple(
        snapshot
        for snapshot in registry.snapshots(section)
        if snapshot.source_sha256 == source_sha
    )
    if len(matches) != 1:
        raise ValueError(
            f"A-C3 expected exactly one {section!r} ConfigSnapshot for {source_path}; "
            f"found {len(matches)}"
        )
    return matches[0]


def _artifact(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise FileNotFoundError(path)
    return {
        "path": str(path),
        "sha256": _sha256(path),
        "size_bytes": path.stat().st_size,
    }


@dataclass(frozen=True, slots=True)
class AshareHistoricalAcceptanceConfig:
    config_path: Path
    repository_root: Path
    development_config: Path
    robust_config: Path
    portfolio_config: Path
    state_root: Path
    acceptance_report: Path
    requested_by: str
    git_sha: str
    verify_content: bool
    factor_rolling_window: int
    mode: AshareHistoricalAcceptanceMode

    @classmethod
    def read_toml(cls, path: str | Path) -> AshareHistoricalAcceptanceConfig:
        config_path = Path(path).expanduser().resolve()
        values = _table(config_path, "ashare_historical_acceptance")
        repository_root = _resolve(Path.cwd(), values.get("repository_root", "."))
        mode = str(values.get("mode", "real_local_dataset"))
        if mode not in {"real_local_dataset", "ci_contract_fixture"}:
            raise ValueError("A-C3 mode must be real_local_dataset or ci_contract_fixture")
        rolling = int(cast(Any, values.get("factor_rolling_window", 20)))
        if rolling < 2:
            raise ValueError("factor_rolling_window must be >= 2")
        requested_by = str(values.get("requested_by", "ac3-local-runner")).strip()
        if not requested_by:
            raise ValueError("requested_by is required")
        return cls(
            config_path=config_path,
            repository_root=repository_root,
            development_config=_resolve(repository_root, values["development_config"]),
            robust_config=_resolve(repository_root, values["robust_config"]),
            portfolio_config=_resolve(repository_root, values["portfolio_config"]),
            state_root=_resolve(repository_root, values.get("state_root", ".finagent/ac3")),
            acceptance_report=_resolve(
                repository_root,
                values.get(
                    "acceptance_report",
                    "reports/ashare_historical_acceptance_ac3.json",
                ),
            ),
            requested_by=requested_by,
            git_sha=str(values.get("git_sha", "")).strip(),
            verify_content=bool(values.get("verify_content", False)),
            factor_rolling_window=rolling,
            mode=cast(AshareHistoricalAcceptanceMode, mode),
        )

    @property
    def config_roots(self) -> tuple[Path, ...]:
        return (
            self.config_path,
            self.development_config,
            self.robust_config,
            self.portfolio_config,
        )


@dataclass(frozen=True, slots=True)
class AshareHistoricalAcceptanceArtifacts:
    certification_report: Path
    development_report: Path
    robust_report: Path
    a4_report: Path
    a4_ledger: Path
    factor_manifest: Path
    strategy_manifest: Path
    market_bar_manifest: Path
    review_bundle: Path
    command_store: Path
    dataset_root: Path | None = None
    frozen_manifest: Path | None = None
    evidence_roots: tuple[Path, ...] = ()

    @property
    def all_files(self) -> tuple[Path, ...]:
        return (
            self.certification_report,
            self.development_report,
            self.robust_report,
            self.a4_report,
            self.a4_ledger,
            self.factor_manifest,
            self.strategy_manifest,
            self.market_bar_manifest,
            self.review_bundle,
            self.command_store,
        )


@dataclass(frozen=True, slots=True)
class AshareHistoricalAcceptanceResult:
    payload: Mapping[str, object]
    report_path: Path

    @property
    def accepted(self) -> bool:
        return bool(self.payload.get("accepted"))

    @property
    def contract_valid(self) -> bool:
        return bool(self.payload.get("contract_valid"))


def _command_records(store: SQLiteCommandStore) -> dict[str, object]:
    records = store.list(limit=500)
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


def verify_ashare_historical_acceptance(
    *,
    artifacts: AshareHistoricalAcceptanceArtifacts,
    mode: AshareHistoricalAcceptanceMode,
    git_sha: str = "",
    verify_dataset_content: bool = False,
    report_path: str | Path | None = None,
) -> AshareHistoricalAcceptanceResult:
    """Verify one fully materialized historical evidence chain.

    CI may exercise this verifier with ``ci_contract_fixture``. Such a run can make
    ``contract_valid`` true, but ``accepted`` is deliberately forced false. Only a
    ``real_local_dataset`` run with full frozen-data content verification can close
    A-C3.
    """

    for artifact_path in artifacts.all_files:
        if not artifact_path.is_file():
            raise FileNotFoundError(artifact_path)

    certification = _load_json(artifacts.certification_report, "certification report")
    development = _load_json(artifacts.development_report, "development report")
    robust = _load_json(artifacts.robust_report, "A2.6 report")
    a4 = _load_json(artifacts.a4_report, "A4 report")
    strategy = StrategyDecisionSeriesProjection(artifacts.strategy_manifest)
    factors = FactorSeriesProjection(artifacts.factor_manifest)
    market_bars = MarketBarSeriesEvidence(artifacts.market_bar_manifest)
    store = SQLiteCommandStore(artifacts.command_store)
    command_records = _command_records(store)

    development_reserve = _mapping(development.get("reserve"), "development reserve")
    robust_result_id = str(robust.get("program_result_id", ""))
    robust_program = _mapping(robust.get("program_spec"), "program_spec")
    robust_reserve = _mapping(robust.get("reserve"), "robust reserve")
    robust_acceptance = _mapping(robust.get("system_acceptance"), "system_acceptance")
    a4_spec = _mapping(a4.get("validation_spec"), "validation_spec")
    a4_reserve = _mapping(a4.get("reserve"), "A4 reserve")
    a4_acceptance = _mapping(a4.get("system_acceptance"), "A4 system_acceptance")
    validation_id = str(a4.get("portfolio_validation_id", ""))
    data_version = str(robust.get("data_version", ""))
    development_acceptance_id = str(development.get("acceptance_id", ""))

    real_dataset_attested = False
    dataset_payload: dict[str, object] = {
        "mode": mode,
        "root": str(artifacts.dataset_root) if artifacts.dataset_root else None,
        "frozen_manifest": (
            str(artifacts.frozen_manifest) if artifacts.frozen_manifest else None
        ),
        "verify_content": bool(verify_dataset_content),
        "content_hashed": False,
        "content_verified": False,
    }
    if mode == "real_local_dataset":
        if artifacts.dataset_root is None or artifacts.frozen_manifest is None:
            raise ValueError("real A-C3 acceptance requires dataset_root and frozen_manifest")
        layout = LocalAshareDatasetLayout(artifacts.dataset_root)
        frozen = LocalAshareFrozenManifest.read_json(artifacts.frozen_manifest)
        if AshareBarFrequency.DAILY.value not in frozen.frequencies:
            raise ValueError("A-C3 frozen dataset must include daily A-share data")
        frozen.verify(layout, verify_content=verify_dataset_content)
        content_verified = bool(verify_dataset_content and frozen.content_hashed)
        dataset_payload.update(
            {
                "dataset_version": frozen.dataset_version,
                "manifest_sha256": _sha256(artifacts.frozen_manifest),
                "content_hashed": frozen.content_hashed,
                "content_verified": content_verified,
            }
        )
        real_dataset_attested = (
            content_verified and frozen.dataset_version == data_version
        )

    roots = artifacts.evidence_roots or tuple(
        sorted(
            {
                artifacts.development_report.parent,
                artifacts.robust_report.parent,
                artifacts.a4_report.parent,
                artifacts.factor_manifest.parent,
                artifacts.strategy_manifest.parent,
                artifacts.market_bar_manifest.parent,
            },
            key=lambda path: path.as_posix(),
        )
    )
    app = create_workspace_app(
        report_paths=roots,
        config_paths=(),
        command_store_path=artifacts.command_store,
        frontend_dir=None,
        git_sha=git_sha,
    )
    strategy_projection = app.state.strategy_explorer
    factor_projection = app.state.factor_tearsheet
    portfolio_projection = app.state.portfolio_execution
    linked = app.state.linked_analytics_acceptance.status()

    strategy_item = strategy_projection.by_portfolio(validation_id)
    market_binding = strategy_projection.market_bar_binding(strategy_item.series_id)
    factor_items = [
        item
        for item in factor_projection.catalog().get("items", [])
        if isinstance(item, Mapping)
        and str(item.get("program_result_id", "")) == robust_result_id
    ]
    portfolio_item = portfolio_projection.item(validation_id)

    v4_methods_ok = True
    v4_route_methods: dict[str, list[str]] = {}
    for route in app.routes:
        path = str(getattr(route, "path", ""))
        if not path.startswith("/api/v4/"):
            continue
        methods = set(getattr(route, "methods", set()) or set())
        v4_route_methods[path] = sorted(methods)
        if not methods <= AC3_EVIDENCE_METHODS:
            v4_methods_ok = False

    review_ok = (
        zipfile.is_zipfile(artifacts.review_bundle)
        and artifacts.review_bundle.stat().st_size > 0
    )
    strategy_manifest = strategy.manifest
    factor_manifest = factors.manifest
    market_manifest = market_bars.manifest

    command_trace_ok = all(
        _command_ok(command_records, command) for command in AC3_REQUIRED_COMMANDS
    )
    development_record = _mapping(
        command_records.get("research.run_development"),
        "development command record",
    )
    robust_record = _mapping(
        command_records.get("research.run_a2p6"),
        "robust command record",
    )
    a4_record = _mapping(
        command_records.get("portfolio.run_a4"),
        "A4 command record",
    )
    review_record = _mapping(
        command_records.get("review.export_bundle"),
        "review command record",
    )
    development_evidence = tuple(
        str(value) for value in development_record.get("evidence_ids", ())
    )
    robust_evidence = tuple(str(value) for value in robust_record.get("evidence_ids", ()))
    a4_evidence = tuple(str(value) for value in a4_record.get("evidence_ids", ()))
    review_evidence = tuple(str(value) for value in review_record.get("evidence_ids", ()))

    checks: dict[str, bool] = {
        "git_sha_recorded": bool(git_sha.strip()),
        "certification_schema": (
            certification.get("schema_version") == "finagent.local-ashare-certification.v1"
        ),
        "certification_passed": certification.get("passed") is True,
        "development_report_schema": (
            development.get("schema_version")
            == "finagent.ashare-factor-research-acceptance.v2"
        ),
        "development_system_acceptance_passed": development.get("passed") is True,
        "development_reserve_untouched": (
            str(development_reserve.get("status", "")) == "untouched"
        ),
        "development_data_version_matches_robust": (
            str(development.get("data_version", "")) == data_version
        ),
        "robust_program_frozen": str(robust.get("program_status", "")) == "frozen",
        "robust_system_acceptance_passed": robust_acceptance.get("passed") is True,
        "robust_reserve_untouched": str(robust_reserve.get("status", "")) == "untouched",
        "a4_system_acceptance_passed": a4_acceptance.get("passed") is True,
        "a4_reserve_untouched": str(a4_reserve.get("status", "")) == "untouched",
        "a4_binds_robust_program": (
            str(a4_spec.get("source_program_result_id", "")) == robust_result_id
        ),
        "a4_data_version_matches_robust": (
            str(a4_spec.get("data_version", "")) == data_version
        ),
        "strategy_verified_nonempty": strategy_manifest.row_count > 0,
        "strategy_binds_a4": strategy_manifest.portfolio_validation_id == validation_id,
        "strategy_binds_robust": (
            strategy_manifest.source_program_result_id == robust_result_id
        ),
        "strategy_data_version_matches": strategy_manifest.data_version == data_version,
        "factor_verified_nonempty": factor_manifest.row_count > 0,
        "factor_binds_robust": factor_manifest.program_result_id == robust_result_id,
        "factor_data_version_matches": factor_manifest.data_version == data_version,
        "market_bars_verified_nonempty": market_manifest.row_count > 0,
        "market_bars_daily": market_manifest.interval.value == "1d",
        "market_bars_bind_strategy": (
            market_manifest.linked_strategy_series_id == strategy_manifest.series_id
        ),
        "market_bars_bind_a4": market_manifest.portfolio_validation_id == validation_id,
        "market_bars_data_version_matches": market_manifest.data_version == data_version,
        "workbench_strategy_identity_exact": (
            strategy_item.series_id == strategy_manifest.series_id
        ),
        "workbench_market_bar_identity_exact": (
            isinstance(market_binding, Mapping)
            and str(market_binding.get("series_id", "")) == market_manifest.series_id
        ),
        "workbench_factor_identity_exact": (
            len(factor_items) == 1
            and str(factor_items[0].get("series_id", "")) == factor_manifest.series_id
        ),
        "workbench_portfolio_identity_exact": (
            portfolio_item.strategy_series_id == strategy_manifest.series_id
        ),
        "linked_analytics_accepted": linked.get("accepted") is True,
        "linked_analytics_no_browser_recompute": (
            linked.get("browser_recomputation") is False
        ),
        "linked_analytics_explicit_missing_policy": (
            linked.get("missing_evidence_policy") == "explicit_unavailable_not_inferred"
        ),
        "linked_analytics_context_contract": set(
            cast(Sequence[str], linked.get("context_keys", ()))
        )
        >= {
            "program_id",
            "factor_id",
            "portfolio_validation_id",
            "asset_id",
            "order_id",
            "date_range",
            "session_date",
            "fold_id",
        },
        "evidence_plane_v4_get_only": v4_methods_ok,
        "command_runs_complete": command_trace_ok,
        "command_run_development_evidence_exact": (
            bool(development_acceptance_id)
            and development_acceptance_id in development_evidence
        ),
        "command_run_robust_evidence_exact": robust_result_id in robust_evidence,
        "command_run_a4_evidence_exact": validation_id in a4_evidence,
        "command_run_review_evidence_exact": validation_id in review_evidence,
        "review_bundle_valid_zip": review_ok,
    }

    contract_valid = all(checks.values())
    accepted = (
        contract_valid
        and mode == "real_local_dataset"
        and real_dataset_attested
    )
    acceptance_id = _digest(
        AC3_ACCEPTANCE_ID_PREFIX,
        {
            "mode": mode,
            "git_sha": git_sha,
            "data_version": data_version,
            "development_acceptance_id": development_acceptance_id,
            "robust_result_id": robust_result_id,
            "portfolio_validation_id": validation_id,
            "strategy_series_id": strategy_manifest.series_id,
            "factor_series_id": factor_manifest.series_id,
            "market_bar_series_id": market_manifest.series_id,
            "review_bundle_sha256": _sha256(artifacts.review_bundle),
            "checks": checks,
            "real_dataset_attested": real_dataset_attested,
        },
    )
    payload: dict[str, object] = {
        "schema_version": AC3_ACCEPTANCE_SCHEMA,
        "acceptance_id": acceptance_id,
        "stage": "A-C3",
        "mode": mode,
        "contract_valid": contract_valid,
        "accepted": accepted,
        "real_dataset_attested": real_dataset_attested,
        "acceptance_semantics": (
            "CI contract fixtures may validate the verifier but can never set accepted=true; "
            "A-C3 closes only after a real_local_dataset run records git_sha and verifies "
            "a content-hashed frozen local dataset with verify_content=true."
        ),
        "git_sha": git_sha,
        "data": dataset_payload,
        "identities": {
            "development_acceptance_id": development_acceptance_id,
            "program_result_id": robust_result_id,
            "program_id": str(robust_program.get("program_id", "")),
            "portfolio_validation_id": validation_id,
            "strategy_series_id": strategy_manifest.series_id,
            "factor_series_id": factor_manifest.series_id,
            "market_bar_series_id": market_manifest.series_id,
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
            "certification": _artifact(artifacts.certification_report),
            "development": _artifact(artifacts.development_report),
            "robust": _artifact(artifacts.robust_report),
            "a4": _artifact(artifacts.a4_report),
            "a4_ledger": _artifact(artifacts.a4_ledger),
            "factor_manifest": _artifact(artifacts.factor_manifest),
            "strategy_manifest": _artifact(artifacts.strategy_manifest),
            "market_bar_manifest": _artifact(artifacts.market_bar_manifest),
            "review_bundle": _artifact(artifacts.review_bundle),
            "command_store": _artifact(artifacts.command_store),
        },
    }

    target = (
        Path(report_path).expanduser().resolve()
        if report_path
        else artifacts.a4_report.with_name("ashare_historical_acceptance_ac3.json")
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return AshareHistoricalAcceptanceResult(payload=payload, report_path=target)


class AshareHistoricalAcceptanceRunner:
    """Host-side A-C3 runner over reviewed historical L0/L1 services.

    Financial/research commands execute in-process through the same typed application
    services used by the Historical Control Plane and are persisted to a dedicated
    SQLiteCommandStore. V4 evidence materializers remain host-only deterministic
    transforms and are invoked with argv lists (never shell strings).
    """

    def __init__(
        self,
        config: AshareHistoricalAcceptanceConfig,
        *,
        confirmed: bool,
    ) -> None:
        self.config = config
        self.confirmed = bool(confirmed)
        self.registry = ConfigRegistry(config.config_roots)
        self.catalog = default_historical_command_catalog()
        self.services = historical_application_service_registry(self.registry)
        self.development_values = _table(
            config.development_config,
            "local_ashare_factor_research",
        )
        self.robust_values = _table(
            config.robust_config,
            "local_ashare_robust_research",
        )
        self.portfolio_values = _table(
            config.portfolio_config,
            "ashare_portfolio_validation",
        )
        self.certification_snapshot = _snapshot_for(
            self.registry,
            section="local_ashare",
            source_path=config.config_path,
        )
        self.development_snapshot = _snapshot_for(
            self.registry,
            section="local_ashare_factor_research",
            source_path=config.development_config,
        )
        self.robust_snapshot = _snapshot_for(
            self.registry,
            section="local_ashare_robust_research",
            source_path=config.robust_config,
        )
        self.portfolio_snapshot = _snapshot_for(
            self.registry,
            section="ashare_portfolio_validation",
            source_path=config.portfolio_config,
        )

        dataset_roots = {
            _resolve(config.repository_root, values["root"])
            for values in (
                self.development_values,
                self.robust_values,
                self.portfolio_values,
            )
        }
        frozen_manifests = {
            _resolve(config.repository_root, values["frozen_manifest"])
            for values in (
                self.development_values,
                self.robust_values,
                self.portfolio_values,
            )
        }
        if len(dataset_roots) != 1 or len(frozen_manifests) != 1:
            raise ValueError(
                "A-C3 requires development, A2.6 and A4 to share one dataset root "
                "and one frozen manifest"
            )
        self.dataset_root = next(iter(dataset_roots))
        self.frozen_manifest = next(iter(frozen_manifests))
        if not self.frozen_manifest.is_file():
            raise FileNotFoundError(self.frozen_manifest)

        robust_report_path = _resolve(
            config.repository_root,
            self.robust_values["report_path"],
        )
        portfolio_source = _resolve(
            config.repository_root,
            self.portfolio_values["a2p6_report"],
        )
        if portfolio_source != robust_report_path:
            raise ValueError(
                "A-C3 A4 config must consume the exact robust report produced by the "
                "A2.6 config"
            )

        seed = {
            "acceptance_config_sha256": _sha256(config.config_path),
            "development_config_sha256": _sha256(config.development_config),
            "robust_config_sha256": _sha256(config.robust_config),
            "portfolio_config_sha256": _sha256(config.portfolio_config),
            "frozen_manifest_sha256": _sha256(self.frozen_manifest),
            "git_sha": config.git_sha,
        }
        self.run_id = _digest("ac3-run", seed, 32)
        self.state_dir = config.state_root / self.run_id
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.command_store_path = self.state_dir / "commands.sqlite"
        self.store = SQLiteCommandStore(self.command_store_path)

    def _audited_command(
        self,
        command_id: str,
        *,
        snapshot: ConfigSnapshot | None = None,
        parameters: Mapping[str, object] | None = None,
        context: Mapping[str, str] | None = None,
    ) -> Any:
        spec = self.catalog.get(command_id)
        if spec.level not in {"L0", "L1"}:
            raise RuntimeError(f"A-C3 refuses non-L0/L1 command {command_id}")
        if spec.gateway_readiness != "application_service_ready":
            raise RuntimeError(f"A-C3 command is not application-service ready: {command_id}")
        if HISTORICAL_APPLICATION_SERVICE_BINDINGS.get(command_id) != spec.binding_ref:
            raise RuntimeError(f"A-C3 catalog/service binding drift: {command_id}")
        if spec.requires_confirmation and not self.confirmed:
            raise PermissionError(f"A-C3 command requires --confirm: {command_id}")
        if snapshot is not None and snapshot.redacted_fields:
            raise RuntimeError(
                f"A-C3 cannot execute redacted ConfigSnapshot {snapshot.snapshot_id}; "
                "bind secrets at the host application-service boundary instead"
            )
        if spec.config_descriptor_ids:
            if snapshot is None:
                raise ValueError(f"A-C3 command requires ConfigSnapshot: {command_id}")
            if snapshot.descriptor_id not in spec.config_descriptor_ids:
                raise ValueError(
                    f"A-C3 ConfigSnapshot descriptor is not allowed for {command_id}"
                )
        elif snapshot is not None:
            raise ValueError(f"A-C3 command does not accept ConfigSnapshot: {command_id}")

        normalized_parameters = dict(parameters or {})
        normalized_context = dict(context or {})
        request_key = f"{self.run_id}:{command_id}"
        record, created = self.store.create(
            request_key=request_key,
            command_id=command_id,
            config_snapshot_id=snapshot.snapshot_id if snapshot else None,
            context=normalized_context,
            parameters=normalized_parameters,
            requested_by=self.config.requested_by,
            accepted=True,
        )
        if not created:
            if record.run.state != "succeeded":
                raise RuntimeError(
                    f"existing A-C3 CommandRun is not succeeded: "
                    f"{command_id}={record.run.state}"
                )
            return record

        self.store.mark_running(record.run.command_run_id)
        invocation = ApplicationCommandInvocation(
            command_id=command_id,
            config_snapshot_id=snapshot.snapshot_id if snapshot else None,
            config_values=snapshot.values if snapshot else {},
            parameters=normalized_parameters,
            context=normalized_context,
            requested_by=self.config.requested_by,
        )
        try:
            execution = self.services.execute(invocation)
            if execution.status == "succeeded":
                self.store.mark_succeeded(record.run.command_run_id, execution)
            else:
                self.store.mark_rejected(record.run.command_run_id, execution)
        except Exception as exc:
            self.store.mark_failed(
                record.run.command_run_id,
                f"{type(exc).__name__}: {exc}",
            )
            raise
        final = self.store.get(record.run.command_run_id)
        if final.run.state != "succeeded":
            message = final.result.message if final.result else final.run.state
            raise RuntimeError(f"A-C3 command failed: {command_id}: {message}")
        return final

    def _materialize(self, arguments: Sequence[str]) -> None:
        completed = subprocess.run(
            [sys.executable, *arguments],
            cwd=self.config.repository_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            stdout = completed.stdout[-4000:]
            stderr = completed.stderr[-4000:]
            raise RuntimeError(
                "A-C3 host materializer failed: "
                f"argv={list(arguments)!r}\nstdout={stdout}\nstderr={stderr}"
            )

    @staticmethod
    def _report_path(record: Any) -> Path:
        outputs = record.outputs or {}
        value = outputs.get("report_path")
        if not value:
            raise ValueError(
                f"CommandRun {record.run.command_run_id} has no report_path"
            )
        return Path(str(value)).expanduser().resolve()

    def run(self) -> AshareHistoricalAcceptanceResult:
        if self.config.mode != "real_local_dataset":
            raise ValueError("A-C3 execution runner only accepts mode=real_local_dataset")
        if not self.confirmed:
            raise PermissionError("A-C3 real execution requires explicit --confirm")
        if not self.config.git_sha:
            raise ValueError("A-C3 real execution requires an exact git_sha")
        if not self.config.verify_content:
            raise ValueError(
                "A-C3 real acceptance requires verify_content=true; metadata-only "
                "frozen-manifest verification cannot close the stage"
            )
        frozen = LocalAshareFrozenManifest.read_json(self.frozen_manifest)
        if not frozen.content_hashed:
            raise ValueError(
                "A-C3 real acceptance requires a content-hashed frozen manifest; "
                "re-freeze the local A-share dataset with content_hash=true"
            )

        certification_report = self.state_dir / "local_ashare_certification.json"
        self._audited_command(
            "data.certify_local_ashare",
            snapshot=self.certification_snapshot,
            parameters={
                "root": str(self.dataset_root),
                "frequency": AshareBarFrequency.DAILY.value,
                "output": str(certification_report),
            },
        )
        development = self._audited_command(
            "research.run_development",
            snapshot=self.development_snapshot,
        )
        robust = self._audited_command(
            "research.run_a2p6",
            snapshot=self.robust_snapshot,
        )
        a4 = self._audited_command(
            "portfolio.run_a4",
            snapshot=self.portfolio_snapshot,
        )

        development_report = self._report_path(development)
        robust_report = self._report_path(robust)
        a4_report = self._report_path(a4)
        a4_payload = _load_json(a4_report, "A4 report")
        validation_id = str(a4_payload.get("portfolio_validation_id", ""))
        if not validation_id:
            raise ValueError("A-C3 A4 report has no portfolio_validation_id")
        ledger_path = _resolve(
            self.config.repository_root,
            self.portfolio_values.get(
                "ledger_path",
                "reports/ashare_a4_ledger.jsonl",
            ),
        )

        factor_manifest = robust_report.with_name(
            f"{robust_report.stem}.factor-series.json"
        )
        strategy_manifest = a4_report.with_name(
            f"{a4_report.stem}.strategy-decisions.json"
        )
        market_bar_manifest = strategy_manifest.with_name(
            f"{strategy_manifest.name.removesuffix('.json')}.market-bars.json"
        )

        factor_args = [
            str(self.config.repository_root / "scripts/materialize_factor_series.py"),
            str(self.config.robust_config),
            "--rolling-window",
            str(self.config.factor_rolling_window),
        ]
        strategy_args = [
            str(
                self.config.repository_root
                / "scripts/materialize_strategy_decision_series.py"
            ),
            str(self.config.portfolio_config),
        ]
        market_args = [
            str(
                self.config.repository_root
                / "scripts/materialize_local_ashare_market_bars.py"
            ),
            str(strategy_manifest),
            "--root",
            str(self.dataset_root),
            "--frozen-manifest",
            str(self.frozen_manifest),
            "--frequency",
            AshareBarFrequency.DAILY.value,
        ]
        factor_args.append("--verify-content")
        strategy_args.append("--verify-content")
        market_args.append("--verify-content")

        self._materialize(factor_args)
        self._materialize(strategy_args)
        self._materialize(market_args)

        evidence_roots = tuple(
            sorted(
                {development_report.parent, robust_report.parent, a4_report.parent},
                key=lambda path: path.as_posix(),
            )
        )
        review_bundle = self.state_dir / f"finagent-review-{validation_id}.zip"
        self._audited_command(
            "review.export_bundle",
            parameters={
                "validation_id": validation_id,
                "reports": tuple(str(path) for path in evidence_roots),
                "output": str(review_bundle),
                "git_sha": self.config.git_sha,
            },
            context={"portfolio_validation_id": validation_id},
        )

        artifacts = AshareHistoricalAcceptanceArtifacts(
            certification_report=certification_report,
            development_report=development_report,
            robust_report=robust_report,
            a4_report=a4_report,
            a4_ledger=ledger_path,
            factor_manifest=factor_manifest,
            strategy_manifest=strategy_manifest,
            market_bar_manifest=market_bar_manifest,
            review_bundle=review_bundle,
            command_store=self.command_store_path,
            dataset_root=self.dataset_root,
            frozen_manifest=self.frozen_manifest,
            evidence_roots=evidence_roots,
        )
        return verify_ashare_historical_acceptance(
            artifacts=artifacts,
            mode=self.config.mode,
            git_sha=self.config.git_sha,
            verify_dataset_content=True,
            report_path=self.config.acceptance_report,
        )