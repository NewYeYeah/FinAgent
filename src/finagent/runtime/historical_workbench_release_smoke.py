from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tomllib
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from fastapi.testclient import TestClient

from finagent.runtime.ashare_historical_v1_freeze import (
    AC5_FREEZE_ID_PREFIX,
    AC5_FREEZE_SCHEMA,
)
from finagent.visualization.workbench_api import create_workspace_app

HISTORICAL_WORKBENCH_RELEASE_SMOKE_SCHEMA = (
    "finagent.historical-workbench-release-smoke.v1"
)
HISTORICAL_WORKBENCH_RELEASE_SMOKE_ID_PREFIX = "historical-workbench-rs"

HistoricalWorkbenchReleaseSmokeMode = Literal[
    "real_frozen_release",
    "ci_contract_fixture",
]
BrowserSmokeStatus = Literal["passed", "failed", "not_run"]

# Product paths whose drift would make a post-freeze UI smoke describe a different
# Workbench than the one bound by A-C5. HW-1.0-RS implementation/tests/docs live
# outside this denominator and may be added after the A-C5 release SHA.
WORKBENCH_PRODUCT_PATHS = (
    "src/finagent/visualization",
    "src/finagent/backtest/strategy_decision_series.py",
    "src/finagent/research/factor_series.py",
    "src/finagent/data/market_bar_series.py",
    "src/finagent/domain/market_bars.py",
    "workspace/src",
    "workspace/package.json",
    "workspace/package-lock.json",
    "workspace/vite.config.ts",
    "scripts/run_workspace.py",
)

_SHA_RE = re.compile(r"[0-9a-f]{40}")


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
    raw = hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()
    return f"{prefix}-{raw[:length]}"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be a mapping")
    return cast(Mapping[str, Any], value)


def _sequence(value: object) -> Sequence[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return cast(Sequence[Any], value)
    return ()


def _load_json(path: Path, name: str) -> Mapping[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    return _mapping(raw, name)


def _resolve(root: Path, value: object) -> Path:
    path = Path(str(value)).expanduser()
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _full_sha(value: object, name: str) -> str:
    text = str(value).strip().lower()
    if _SHA_RE.fullmatch(text) is None:
        raise ValueError(f"{name} must be a full 40-character lowercase Git SHA")
    return text


def _git(
    repository_root: Path,
    *args: str,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=repository_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if check and result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"git {' '.join(args)} failed: {detail}")
    return result


def _resolve_git_sha(repository_root: Path, explicit: str | None) -> str:
    if explicit:
        sha = _full_sha(explicit, "smoke_git_sha")
    else:
        sha = _full_sha(
            _git(repository_root, "rev-parse", "HEAD").stdout.strip(),
            "smoke_git_sha",
        )
    _git(repository_root, "cat-file", "-e", f"{sha}^{{commit}}")
    return sha


def _is_ancestor(repository_root: Path, ancestor: str, descendant: str) -> bool:
    return (
        _git(
            repository_root,
            "merge-base",
            "--is-ancestor",
            ancestor,
            descendant,
            check=False,
        ).returncode
        == 0
    )


def _workbench_product_drift(
    repository_root: Path,
    *,
    freeze_sha: str,
    smoke_sha: str,
) -> tuple[str, ...]:
    if freeze_sha == smoke_sha:
        return ()
    result = _git(
        repository_root,
        "diff",
        "--name-only",
        f"{freeze_sha}..{smoke_sha}",
        "--",
        *WORKBENCH_PRODUCT_PATHS,
    )
    return tuple(line.strip() for line in result.stdout.splitlines() if line.strip())


def recompute_ac5_freeze_id(payload: Mapping[str, Any]) -> str:
    """Recompute the A-C5 release identity without rerunning A-C5 or research."""

    material = {
        "schema_version": payload.get("schema_version"),
        "release_name": payload.get("release_name"),
        "release_git_sha": payload.get("release_git_sha"),
        "mode": payload.get("mode"),
        "ac3": payload.get("ac3"),
        "ac4_audit_id": payload.get("ac4_audit_id"),
        "deferred_capabilities": payload.get("deferred_capabilities"),
        "artifacts": payload.get("artifacts"),
        "reserve": payload.get("reserve"),
    }
    return _digest(AC5_FREEZE_ID_PREFIX, material)


def _artifact_descriptor(
    freeze: Mapping[str, Any],
    role: str,
) -> Mapping[str, Any]:
    matches = [
        _mapping(item, f"A-C5 artifact {role}")
        for item in _sequence(freeze.get("artifacts"))
        if isinstance(item, Mapping) and str(item.get("role", "")) == role
    ]
    if len(matches) != 1:
        raise ValueError(
            f"A-C5 freeze must contain exactly one {role!r} artifact; found {len(matches)}"
        )
    return matches[0]


def _verify_descriptor(path: Path, descriptor: Mapping[str, Any], name: str) -> None:
    if not path.is_file():
        raise FileNotFoundError(path)
    expected_sha = str(descriptor.get("sha256", "")).strip()
    expected_size = int(cast(Any, descriptor.get("size_bytes", -1)))
    if _sha256(path) != expected_sha or path.stat().st_size != expected_size:
        raise ValueError(f"{name} SHA-256/size differs from the A-C5 freeze")


def _a3_artifact_paths(
    ac3: Mapping[str, Any],
    repository_root: Path,
) -> tuple[dict[str, Path], tuple[Path, ...]]:
    raw = _mapping(ac3.get("artifacts"), "A-C3 artifacts")
    paths: dict[str, Path] = {}
    report_roots: set[Path] = set()
    for role, value in raw.items():
        if value is None:
            continue
        descriptor = _mapping(value, f"A-C3 artifact {role}")
        path = _resolve(repository_root, descriptor.get("path", ""))
        _verify_descriptor(path, descriptor, f"A-C3 artifact {role}")
        paths[str(role)] = path
        if path.suffix.lower() in {".json", ".jsonl", ".parquet"}:
            report_roots.add(path.parent)
    required = {"robust", "a4", "factor_manifest", "strategy_manifest", "command_store"}
    missing = sorted(required - set(paths))
    if missing:
        raise ValueError("A-C3 Workbench evidence is incomplete: " + ", ".join(missing))
    return paths, tuple(sorted(report_roots, key=lambda value: value.as_posix()))


@dataclass(frozen=True, slots=True)
class HistoricalWorkbenchReleaseSmokeConfig:
    config_path: Path
    repository_root: Path
    freeze_report: Path
    freeze_package: Path
    ac3_report: Path
    config_roots: tuple[Path, ...]
    frontend_dir: Path
    output_json: Path
    output_markdown: Path
    mode: HistoricalWorkbenchReleaseSmokeMode
    smoke_git_sha: str | None
    host: str
    port: int
    build_frontend: bool
    run_browser: bool

    @classmethod
    def read_toml(cls, path: str | Path) -> HistoricalWorkbenchReleaseSmokeConfig:
        config_path = Path(path).expanduser().resolve()
        with config_path.open("rb") as handle:
            raw = tomllib.load(handle)
        values = raw.get("historical_workbench_release_smoke")
        if not isinstance(values, Mapping):
            raise TypeError(
                f"{config_path} must contain [historical_workbench_release_smoke]"
            )
        repository_root = _resolve(Path.cwd(), values.get("repository_root", "."))
        mode_raw = str(values.get("mode", "real_frozen_release")).strip()
        if mode_raw not in {"real_frozen_release", "ci_contract_fixture"}:
            raise ValueError(
                "mode must be real_frozen_release or ci_contract_fixture"
            )
        raw_configs = values.get("config_roots", ["configs"])
        if not isinstance(raw_configs, list):
            raise TypeError("config_roots must be an array")
        config_roots = tuple(_resolve(repository_root, value) for value in raw_configs)
        port = int(cast(Any, values.get("port", 8765)))
        if not 1 <= port <= 65535:
            raise ValueError("port must be in [1, 65535]")
        return cls(
            config_path=config_path,
            repository_root=repository_root,
            freeze_report=_resolve(
                repository_root,
                values.get(
                    "freeze_report",
                    "reports/finagent_ashare_historical_v1_freeze.json",
                ),
            ),
            freeze_package=_resolve(
                repository_root,
                values.get(
                    "freeze_package",
                    "reports/finagent_ashare_historical_v1_freeze.zip",
                ),
            ),
            ac3_report=_resolve(
                repository_root,
                values.get(
                    "ac3_report",
                    "reports/ashare_historical_acceptance_ac3.json",
                ),
            ),
            config_roots=config_roots,
            frontend_dir=_resolve(repository_root, values.get("frontend_dir", "workspace/dist")),
            output_json=_resolve(
                repository_root,
                values.get(
                    "output_json",
                    "reports/historical_workbench_release_smoke.json",
                ),
            ),
            output_markdown=_resolve(
                repository_root,
                values.get(
                    "output_markdown",
                    "reports/historical_workbench_release_smoke.md",
                ),
            ),
            mode=cast(HistoricalWorkbenchReleaseSmokeMode, mode_raw),
            smoke_git_sha=(str(values.get("smoke_git_sha", "")).strip() or None),
            host=str(values.get("host", "127.0.0.1")).strip() or "127.0.0.1",
            port=port,
            build_frontend=bool(values.get("build_frontend", True)),
            run_browser=bool(values.get("run_browser", True)),
        )


@dataclass(frozen=True, slots=True)
class HistoricalWorkbenchReleaseSmokePrepared:
    app: Any
    payload_base: Mapping[str, object]
    expected: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class HistoricalWorkbenchReleaseSmokeResult:
    payload: Mapping[str, object]
    json_path: Path
    markdown_path: Path

    @property
    def contract_valid(self) -> bool:
        return bool(self.payload.get("contract_valid"))

    @property
    def accepted(self) -> bool:
        return bool(self.payload.get("accepted"))


class HistoricalWorkbenchReleaseSmoke:
    """Post-freeze read-only product smoke over the exact A-C5/A-C3 evidence chain."""

    def __init__(self, config: HistoricalWorkbenchReleaseSmokeConfig) -> None:
        self.config = config

    def prepare(self) -> HistoricalWorkbenchReleaseSmokePrepared:
        root = self.config.repository_root
        smoke_sha = _resolve_git_sha(root, self.config.smoke_git_sha)
        freeze = _load_json(self.config.freeze_report, "A-C5 freeze")
        if freeze.get("schema_version") != AC5_FREEZE_SCHEMA or freeze.get("stage") != "A-C5":
            raise ValueError("HW-1.0-RS requires an A-C5 freeze report")
        if freeze.get("contract_valid") is not True:
            raise ValueError("A-C5 freeze contract is not valid")
        if str(freeze.get("freeze_id", "")) != recompute_ac5_freeze_id(freeze):
            raise ValueError("A-C5 freeze_id does not recompute exactly")
        if self.config.mode == "real_frozen_release":
            if freeze.get("frozen") is not True or freeze.get("mode") != "real_local_evidence":
                raise ValueError("real HW-1.0-RS requires frozen real_local_evidence A-C5")

        freeze_sha = _full_sha(freeze.get("release_git_sha"), "A-C5 release_git_sha")
        if not _is_ancestor(root, freeze_sha, smoke_sha):
            raise ValueError("A-C5 release Git SHA is not an ancestor of the smoke verifier")
        product_drift = _workbench_product_drift(
            root,
            freeze_sha=freeze_sha,
            smoke_sha=smoke_sha,
        )
        if product_drift:
            raise ValueError(
                "Workbench product changed after A-C5 freeze: " + ", ".join(product_drift)
            )

        ac3_descriptor = _artifact_descriptor(freeze, "ac3_acceptance")
        _verify_descriptor(self.config.ac3_report, ac3_descriptor, "A-C3 acceptance report")
        ac3 = _load_json(self.config.ac3_report, "A-C3 acceptance")
        frozen_ac3 = _mapping(freeze.get("ac3"), "A-C5 ac3 summary")
        if str(ac3.get("acceptance_id", "")) != str(frozen_ac3.get("acceptance_id", "")):
            raise ValueError("A-C3 acceptance identity differs from A-C5")
        identities = _mapping(ac3.get("identities"), "A-C3 identities")
        frozen_identities = _mapping(frozen_ac3.get("identities"), "A-C5 A-C3 identities")
        if dict(identities) != dict(frozen_identities):
            raise ValueError("A-C3 evidence identities differ from A-C5")

        if not self.config.freeze_package.is_file() or not zipfile.is_zipfile(
            self.config.freeze_package
        ):
            raise ValueError("A-C5 freeze package is missing or is not a ZIP")
        with zipfile.ZipFile(self.config.freeze_package) as archive:
            names = set(archive.namelist())
            freeze_member = "release/freeze/finagent_ashare_historical_v1_freeze.json"
            ac3_member = "release/ac3/ashare_historical_acceptance_ac3.json"
            if freeze_member not in names or ac3_member not in names:
                raise ValueError("A-C5 package does not contain canonical freeze/A-C3 records")
            embedded_freeze = json.loads(archive.read(freeze_member).decode("utf-8"))
            embedded_ac3 = json.loads(archive.read(ac3_member).decode("utf-8"))
        if embedded_freeze != dict(freeze):
            raise ValueError("A-C5 package freeze record differs from external freeze report")
        if embedded_ac3 != dict(ac3):
            raise ValueError("A-C5 package A-C3 record differs from external A-C3 report")

        artifact_paths, report_roots = _a3_artifact_paths(ac3, root)
        command_store = artifact_paths["command_store"]
        app = create_workspace_app(
            report_paths=report_roots,
            config_paths=self.config.config_roots,
            command_store_path=command_store,
            frontend_dir=None,
            git_sha=smoke_sha,
            catalog_db_path=None,
        )
        client = TestClient(app)
        status_response = client.get("/api/v3/workbench/status")
        if status_response.status_code != 200:
            raise ValueError("Workbench status endpoint is unavailable")
        status = _mapping(status_response.json(), "Workbench status")

        validation_id = str(identities.get("portfolio_validation_id", "")).strip()
        strategy_series_id = str(identities.get("strategy_series_id", "")).strip()
        factor_series_id = str(identities.get("factor_series_id", "")).strip()
        program_result_id = str(identities.get("program_result_id", "")).strip()
        if not all((validation_id, strategy_series_id, factor_series_id, program_result_id)):
            raise ValueError("A-C3 lacks Workbench release identities")

        strategy = app.state.strategy_explorer.by_portfolio(validation_id)
        dimensions = app.state.strategy_explorer.dimensions(strategy.series_id)
        factor_catalog = app.state.factor_tearsheet.catalog()
        factor_items = [
            item
            for item in _sequence(factor_catalog.get("items"))
            if isinstance(item, Mapping)
            and str(item.get("program_result_id", "")) == program_result_id
        ]
        portfolio_catalog = app.state.portfolio_execution.catalog()
        portfolio_items = [
            item
            for item in _sequence(portfolio_catalog.get("items"))
            if isinstance(item, Mapping)
            and str(item.get("portfolio_validation_id", "")) == validation_id
        ]
        portfolio_cockpit = app.state.workspace_v2.portfolio_cockpit(validation_id)
        linked = app.state.linked_analytics_acceptance.status()
        research_outcome = str(frozen_ac3.get("research_outcome", "")).strip()

        checks: dict[str, bool] = {
            "freeze_identity_recomputed": True,
            "freeze_package_embeds_exact_records": True,
            "freeze_release_is_ancestor": True,
            "workbench_product_unchanged_since_freeze": not product_drift,
            "workbench_read_only": status.get("read_only") is True,
            "evidence_plane_enabled": status.get("evidence_plane") is True,
            "control_plane_not_embedded": status.get("control_plane_enabled") is False,
            "strategy_identity_exact": strategy.series_id == strategy_series_id,
            "strategy_portfolio_binding_exact": strategy.portfolio_validation_id == validation_id,
            "factor_identity_exact": (
                len(factor_items) == 1
                and str(factor_items[0].get("series_id", "")) == factor_series_id
            ),
            "linked_analytics_accepted": linked.get("accepted") is True,
            "linked_no_browser_recompute": linked.get("browser_recomputation") is False,
            "linked_missing_evidence_policy": (
                linked.get("missing_evidence_policy")
                == "explicit_unavailable_not_inferred"
            ),
            "configuration_surface_available": (
                self.config.mode != "real_frozen_release"
                or int(cast(Any, status.get("config_descriptor_count", 0))) > 0
            ),
        }

        if research_outcome == "NO_ROBUST_FACTOR_FAMILY":
            checks.update(
                {
                    "no_alpha_strategy_explicit_empty": (
                        strategy.row_count == 0
                        and strategy.session_count == 0
                        and strategy.asset_count == 0
                        and strategy.start_date is None
                        and strategy.end_date is None
                    ),
                    "no_alpha_strategy_dimensions_empty": (
                        not tuple(_sequence(dimensions.get("assets")))
                        and int(cast(Any, dimensions.get("session_count", -1))) == 0
                    ),
                    "no_alpha_market_bars_unavailable": (
                        app.state.strategy_explorer.market_bar_binding(strategy.series_id)
                        is None
                    ),
                    "no_alpha_factor_evidence_visible": (
                        len(factor_items) == 1
                        and int(cast(Any, factor_items[0].get("factor_count", 0))) > 0
                    ),
                    "no_alpha_portfolio_explicit_unavailable": (
                        _mapping(portfolio_cockpit, "portfolio cockpit").get("no_portfolio")
                        is True
                    ),
                    "no_alpha_execution_not_fabricated": not portfolio_items,
                }
            )
        elif research_outcome == "POPULATED_STRATEGY":
            checks.update(
                {
                    "populated_strategy_nonempty": strategy.row_count > 0,
                    "populated_factor_evidence_visible": len(factor_items) == 1,
                    "populated_portfolio_execution_visible": len(portfolio_items) == 1,
                }
            )
        else:
            raise ValueError(f"unsupported A-C5 research outcome: {research_outcome!r}")

        contract_valid = all(checks.values())
        base_payload: dict[str, object] = {
            "schema_version": HISTORICAL_WORKBENCH_RELEASE_SMOKE_SCHEMA,
            "stage": "HW-1.0-RS",
            "mode": self.config.mode,
            "freeze_id": str(freeze.get("freeze_id", "")),
            "freeze_release_git_sha": freeze_sha,
            "smoke_git_sha": smoke_sha,
            "freeze_package_sha256": _sha256(self.config.freeze_package),
            "research_outcome": research_outcome,
            "identities": {
                "portfolio_validation_id": validation_id,
                "strategy_series_id": strategy_series_id,
                "factor_series_id": factor_series_id,
                "program_result_id": program_result_id,
                "market_bar_series_id": identities.get("market_bar_series_id"),
            },
            "checks": checks,
            "contract_valid": contract_valid,
            "workbench_product_drift": list(product_drift),
            "authority": "read_only_release_smoke_no_financial_or_operational_authority",
            "production_reserve_consumed": False,
            "browser_recomputation": False,
        }
        expected = {
            "freeze_id": str(freeze.get("freeze_id", "")),
            "research_outcome": research_outcome,
            "portfolio_validation_id": validation_id,
            "strategy_series_id": strategy_series_id,
            "factor_series_id": factor_series_id,
            "program_result_id": program_result_id,
        }
        return HistoricalWorkbenchReleaseSmokePrepared(
            app=app,
            payload_base=base_payload,
            expected=expected,
        )

    def finalize(
        self,
        prepared: HistoricalWorkbenchReleaseSmokePrepared,
        *,
        browser_status: BrowserSmokeStatus,
        browser_detail: str = "",
    ) -> HistoricalWorkbenchReleaseSmokeResult:
        if browser_status not in {"passed", "failed", "not_run"}:
            raise ValueError(f"unsupported browser smoke status: {browser_status}")
        base = dict(prepared.payload_base)
        contract_valid = bool(base.get("contract_valid"))
        browser_required = self.config.mode == "real_frozen_release" and self.config.run_browser
        browser_ok = browser_status == "passed" if browser_required else browser_status != "failed"
        accepted = (
            contract_valid
            and self.config.mode == "real_frozen_release"
            and browser_ok
            and (not browser_required or browser_status == "passed")
        )
        identity_material = {
            "schema_version": HISTORICAL_WORKBENCH_RELEASE_SMOKE_SCHEMA,
            "freeze_id": base.get("freeze_id"),
            "freeze_release_git_sha": base.get("freeze_release_git_sha"),
            "smoke_git_sha": base.get("smoke_git_sha"),
            "research_outcome": base.get("research_outcome"),
            "identities": base.get("identities"),
            "checks": base.get("checks"),
            "browser_status": browser_status,
        }
        payload: dict[str, object] = {
            **base,
            "smoke_id": _digest(
                HISTORICAL_WORKBENCH_RELEASE_SMOKE_ID_PREFIX,
                identity_material,
            ),
            "browser": {
                "required": browser_required,
                "status": browser_status,
                "detail": browser_detail,
            },
            "accepted": accepted,
            "acceptance_semantics": (
                "CI fixtures validate the HW-1.0-RS contract but cannot accept the "
                "real frozen product. Real acceptance requires a frozen A-C5 release, "
                "zero Workbench product drift and a passing production-build Playwright "
                "smoke over the locally verified A-C3 evidence."
            ),
        }
        self.config.output_json.parent.mkdir(parents=True, exist_ok=True)
        self.config.output_json.write_text(
            json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        self.config.output_markdown.write_text(
            self._markdown(payload),
            encoding="utf-8",
        )
        return HistoricalWorkbenchReleaseSmokeResult(
            payload=payload,
            json_path=self.config.output_json,
            markdown_path=self.config.output_markdown,
        )

    @staticmethod
    def _markdown(payload: Mapping[str, object]) -> str:
        identities = _mapping(payload.get("identities"), "HW-1.0-RS identities")
        browser = _mapping(payload.get("browser"), "HW-1.0-RS browser")
        checks = _mapping(payload.get("checks"), "HW-1.0-RS checks")
        lines = [
            "# Historical Workbench 1.0 Post-freeze Release Smoke",
            "",
            f"- Smoke ID: `{payload.get('smoke_id')}`",
            f"- Freeze ID: `{payload.get('freeze_id')}`",
            f"- Freeze Git SHA: `{payload.get('freeze_release_git_sha')}`",
            f"- Smoke Git SHA: `{payload.get('smoke_git_sha')}`",
            f"- Research outcome: `{payload.get('research_outcome')}`",
            f"- Contract valid: `{str(bool(payload.get('contract_valid'))).lower()}`",
            f"- Browser: `{browser.get('status')}`",
            f"- Accepted: `{str(bool(payload.get('accepted'))).lower()}`",
            "",
            "## Frozen identities",
            "",
        ]
        for key in (
            "program_result_id",
            "portfolio_validation_id",
            "strategy_series_id",
            "factor_series_id",
            "market_bar_series_id",
        ):
            lines.append(f"- {key}: `{identities.get(key)}`")
        lines.extend(("", "## Checks", ""))
        for key, value in sorted(checks.items()):
            lines.append(f"- `{key}`: `{str(bool(value)).lower()}`")
        lines.extend(
            (
                "",
                "## Boundary",
                "",
                "This smoke is read-only. It does not rerun research, consume the production "
                "reserve, create orders, enable PAPER or authorize live capital.",
                "",
            )
        )
        return "\n".join(lines)
