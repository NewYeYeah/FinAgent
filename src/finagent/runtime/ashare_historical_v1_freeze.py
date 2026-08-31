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

from finagent.data import LocalAshareFrozenManifest
from finagent.runtime.ashare_historical_acceptance import (
    AC3_ACCEPTANCE_ID_PREFIX,
    AC3_ACCEPTANCE_SCHEMA,
)
from finagent.runtime.initial_requirement_compliance import (
    INITIAL_REQUIREMENT_COMPLIANCE_SCHEMA,
    run_initial_requirement_compliance_audit,
)

AC5_FREEZE_SCHEMA = "finagent.ashare-historical-v1-freeze.v1"
AC5_FREEZE_ID_PREFIX = "ashare-historical-v1"
AC5_RELEASE_NAME = "FinAgent A-share Historical v1.0"

HistoricalFreezeMode = Literal["real_local_evidence", "ci_contract_fixture"]

HISTORICAL_V1_DEFERRED_CAPABILITIES = (
    "advanced_risk",
    "benchmark_evidence",
    "capacity_impact",
    "corporate_actions",
    "internal_paper",
    "qmt",
    "realtime_gateway",
)

# These paths are the historical financial/research product accepted by A-C3.
# A-C4/A-C5 may add release/audit code, but the accepted historical core must not
# silently change between the A-C3 evidence revision and the v1.0 release revision.
HISTORICAL_CORE_PATHS = (
    "src/finagent/application",
    "src/finagent/backtest",
    "src/finagent/data",
    "src/finagent/domain",
    "src/finagent/models",
    "src/finagent/research",
    "src/finagent/services",
    "src/finagent/visualization",
    "src/finagent/runtime/ashare_historical_acceptance.py",
    "src/finagent/runtime/ashare_historical_acceptance_terminal.py",
    "workspace",
    "configs/research",
    "configs/execution",
    "scripts/materialize_factor_series.py",
    "scripts/materialize_strategy_decision_series.py",
    "scripts/materialize_local_ashare_market_bars.py",
    "scripts/run_local_ashare_factor_research.py",
    "scripts/run_local_ashare_robust_research.py",
    "scripts/run_ashare_portfolio_validation.py",
    "scripts/run_workspace.py",
    "scripts/run_workbench_control.py",
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


def _repo_relative(repository_root: Path, path: Path) -> str:
    resolved = path.resolve()
    root = repository_root.resolve()
    if resolved == root or root not in resolved.parents:
        raise ValueError(f"A-C5 repository artifact must live under repository root: {path}")
    return resolved.relative_to(root).as_posix()


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


def _resolve_release_sha(repository_root: Path, explicit: str | None) -> str:
    if explicit:
        sha = _full_sha(explicit, "release_git_sha")
    else:
        sha = _full_sha(
            _git(repository_root, "rev-parse", "HEAD").stdout.strip(),
            "release_git_sha",
        )
    _git(repository_root, "cat-file", "-e", f"{sha}^{{commit}}")
    return sha


def _is_ancestor(repository_root: Path, ancestor: str, descendant: str) -> bool:
    result = _git(
        repository_root,
        "merge-base",
        "--is-ancestor",
        ancestor,
        descendant,
        check=False,
    )
    return result.returncode == 0


def _tracked_worktree_clean(repository_root: Path) -> bool:
    return (
        _git(repository_root, "diff", "--quiet", check=False).returncode == 0
        and _git(repository_root, "diff", "--cached", "--quiet", check=False).returncode == 0
    )


def _historical_core_drift(
    repository_root: Path,
    *,
    evidence_sha: str,
    release_sha: str,
) -> tuple[str, ...]:
    if evidence_sha == release_sha:
        return ()
    result = _git(
        repository_root,
        "diff",
        "--name-only",
        f"{evidence_sha}..{release_sha}",
        "--",
        *HISTORICAL_CORE_PATHS,
    )
    return tuple(line.strip() for line in result.stdout.splitlines() if line.strip())


def _artifact_descriptor(
    role: str,
    path: Path,
    *,
    logical_name: str | None = None,
) -> dict[str, object]:
    if not path.is_file():
        raise FileNotFoundError(path)
    return {
        "role": role,
        "logical_name": logical_name or path.name,
        "sha256": _sha256(path),
        "size_bytes": path.stat().st_size,
    }


def _verify_recorded_artifact(
    role: str,
    raw: object,
) -> tuple[dict[str, object], Path]:
    descriptor = _mapping(raw, f"A-C3 artifact {role}")
    path = Path(str(descriptor.get("path", ""))).expanduser()
    if not path.is_absolute():
        path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    recorded_sha = str(descriptor.get("sha256", "")).strip()
    recorded_size = int(cast(Any, descriptor.get("size_bytes", -1)))
    actual_sha = _sha256(path)
    actual_size = path.stat().st_size
    if recorded_sha != actual_sha or recorded_size != actual_size:
        raise ValueError(f"A-C3 artifact digest/size mismatch for {role}: {path}")
    return (
        {
            "role": f"ac3:{role}",
            "logical_name": path.name,
            "sha256": actual_sha,
            "size_bytes": actual_size,
        },
        path,
    )


def recompute_ac3_acceptance_id(payload: Mapping[str, Any]) -> str:
    """Recompute the existing A-C3 identity without rerunning historical research."""

    identities = _mapping(payload.get("identities"), "A-C3 identities")
    checks = _mapping(payload.get("checks"), "A-C3 checks")
    artifacts = _mapping(payload.get("artifacts"), "A-C3 artifacts")
    review = _mapping(artifacts.get("review_bundle"), "A-C3 review bundle")
    terminal = str(payload.get("terminal_state", "")).strip()
    material: dict[str, object]
    if terminal == "NO_ROBUST_FACTOR_FAMILY":
        material = {
            "terminal_state": terminal,
            "git_sha": str(payload.get("git_sha", "")),
            "data_version": str(identities.get("data_version", "")),
            "development_acceptance_id": str(
                identities.get("development_acceptance_id", "")
            ),
            "program_result_id": str(identities.get("program_result_id", "")),
            "portfolio_validation_id": str(
                identities.get("portfolio_validation_id", "")
            ),
            "strategy_series_id": str(identities.get("strategy_series_id", "")),
            "factor_series_id": str(identities.get("factor_series_id", "")),
            "review_bundle_sha256": str(review.get("sha256", "")),
            "checks": dict(checks),
        }
    elif not terminal:
        material = {
            "mode": str(payload.get("mode", "")),
            "git_sha": str(payload.get("git_sha", "")),
            "data_version": str(identities.get("data_version", "")),
            "development_acceptance_id": str(
                identities.get("development_acceptance_id", "")
            ),
            "robust_result_id": str(identities.get("program_result_id", "")),
            "portfolio_validation_id": str(
                identities.get("portfolio_validation_id", "")
            ),
            "strategy_series_id": str(identities.get("strategy_series_id", "")),
            "factor_series_id": str(identities.get("factor_series_id", "")),
            "market_bar_series_id": str(identities.get("market_bar_series_id", "")),
            "review_bundle_sha256": str(review.get("sha256", "")),
            "checks": dict(checks),
            "real_dataset_attested": bool(payload.get("real_dataset_attested")),
        }
    else:
        raise ValueError(f"unsupported A-C3 terminal_state: {terminal!r}")
    return _digest(AC3_ACCEPTANCE_ID_PREFIX, material)


@dataclass(frozen=True, slots=True)
class HistoricalFreezeConfig:
    config_path: Path
    repository_root: Path
    ac3_report: Path
    ac4_report: Path
    ac4_manifest: Path
    frozen_dataset_manifest: Path
    output_json: Path
    output_markdown: Path
    output_package: Path
    environment_files: tuple[Path, ...]
    mode: HistoricalFreezeMode
    release_git_sha: str | None
    require_clean_tracked_worktree: bool

    @classmethod
    def read_toml(cls, path: str | Path) -> HistoricalFreezeConfig:
        config_path = Path(path).expanduser().resolve()
        with config_path.open("rb") as handle:
            raw = tomllib.load(handle)
        values = raw.get("ashare_historical_v1_freeze")
        if not isinstance(values, dict):
            raise TypeError(
                f"{config_path} must contain [ashare_historical_v1_freeze]"
            )
        repository_root = _resolve(Path.cwd(), values.get("repository_root", "."))
        mode = str(values.get("mode", "real_local_evidence")).strip()
        if mode not in {"real_local_evidence", "ci_contract_fixture"}:
            raise ValueError(
                "A-C5 mode must be real_local_evidence or ci_contract_fixture"
            )
        environment = values.get(
            "environment_files",
            [
                "pyproject.toml",
                "environment/environment.yml",
                "environment/requirements.txt",
                "environment/requirements-dev.txt",
                "workspace/package-lock.json",
            ],
        )
        if not isinstance(environment, list) or not environment:
            raise TypeError("environment_files must be a non-empty array")
        environment_files = tuple(_resolve(repository_root, item) for item in environment)
        for environment_file in environment_files:
            _repo_relative(repository_root, environment_file)
        return cls(
            config_path=config_path,
            repository_root=repository_root,
            ac3_report=_resolve(
                repository_root,
                values.get(
                    "ac3_report",
                    "reports/ashare_historical_acceptance_ac3.json",
                ),
            ),
            ac4_report=_resolve(
                repository_root,
                values.get(
                    "ac4_report",
                    "reports/ashare_initial_requirement_compliance_ac4.json",
                ),
            ),
            ac4_manifest=_resolve(
                repository_root,
                values.get(
                    "ac4_manifest",
                    "configs/acceptance/ashare_initial_requirement_compliance_ac4.toml",
                ),
            ),
            frozen_dataset_manifest=_resolve(
                repository_root,
                values.get(
                    "frozen_dataset_manifest",
                    "data/manifests/local_ashare_daily.json",
                ),
            ),
            output_json=_resolve(
                repository_root,
                values.get(
                    "output_json",
                    "reports/finagent_ashare_historical_v1_freeze.json",
                ),
            ),
            output_markdown=_resolve(
                repository_root,
                values.get(
                    "output_markdown",
                    "reports/finagent_ashare_historical_v1_freeze.md",
                ),
            ),
            output_package=_resolve(
                repository_root,
                values.get(
                    "output_package",
                    "reports/finagent_ashare_historical_v1_freeze.zip",
                ),
            ),
            environment_files=environment_files,
            mode=cast(HistoricalFreezeMode, mode),
            release_git_sha=(str(values.get("release_git_sha", "")).strip() or None),
            require_clean_tracked_worktree=bool(
                values.get("require_clean_tracked_worktree", True)
            ),
        )


@dataclass(frozen=True, slots=True)
class HistoricalFreezeResult:
    payload: Mapping[str, object]
    json_path: Path
    markdown_path: Path
    package_path: Path | None = None
    package_sha256: str | None = None

    @property
    def frozen(self) -> bool:
        return bool(self.payload.get("frozen"))

    @property
    def contract_valid(self) -> bool:
        return bool(self.payload.get("contract_valid"))


class AshareHistoricalV1Freezer:
    """Freeze accepted A-share historical evidence without creating new market claims."""

    def __init__(self, config: HistoricalFreezeConfig) -> None:
        self.config = config

    def _validate_ac4(
        self,
        ac4: Mapping[str, Any],
        release_sha: str,
    ) -> tuple[str, tuple[str, ...]]:
        if ac4.get("schema_version") != INITIAL_REQUIREMENT_COMPLIANCE_SCHEMA:
            raise ValueError("A-C4 report schema mismatch")
        ac4_git_sha = _full_sha(ac4.get("git_sha"), "A-C4 git_sha")
        recomputed = run_initial_requirement_compliance_audit(
            self.config.ac4_manifest,
            repository_root=self.config.repository_root,
            git_sha=ac4_git_sha,
        )
        if dict(ac4) != recomputed.to_dict():
            raise ValueError("A-C4 report does not exactly replay from frozen manifest")
        deferred = tuple(
            sorted(
                str(value) for value in _sequence(ac4.get("deferred_capabilities"))
            )
        )
        if deferred != HISTORICAL_V1_DEFERRED_CAPABILITIES:
            raise ValueError(
                "A-C4 deferred capability set differs from Historical v1.0 freeze"
            )
        if ac4.get("audit_complete") is not True:
            raise ValueError("A-C4 audit is incomplete")
        if ac4.get("historical_freeze_ready") is not True:
            raise ValueError("A-C4 audit is not freeze-ready")
        summary = _mapping(ac4.get("summary"), "A-C4 summary")
        if int(cast(Any, summary.get("PARTIAL", -1))) != 0:
            raise ValueError("A-C4 has PARTIAL requirements")
        if self.config.mode == "real_local_evidence" and ac4_git_sha != release_sha:
            raise ValueError(
                "real A-C5 requires A-C4 to be regenerated on the exact release Git SHA"
            )
        return str(ac4.get("audit_id", "")), deferred

    def _validate_ac3(
        self,
        ac3: Mapping[str, Any],
        release_sha: str,
    ) -> tuple[dict[str, object], list[dict[str, object]], list[tuple[str, Path]]]:
        if ac3.get("schema_version") != AC3_ACCEPTANCE_SCHEMA:
            raise ValueError("A-C3 report schema mismatch")
        if ac3.get("contract_valid") is not True:
            raise ValueError("A-C3 contract is not valid")
        ac3_sha = _full_sha(ac3.get("git_sha"), "A-C3 git_sha")
        if not _is_ancestor(self.config.repository_root, ac3_sha, release_sha):
            raise ValueError("A-C3 Git SHA is not an ancestor of the release Git SHA")
        if str(ac3.get("acceptance_id", "")) != recompute_ac3_acceptance_id(ac3):
            raise ValueError("A-C3 acceptance_id does not recompute exactly")

        data = _mapping(ac3.get("data"), "A-C3 data")
        identities = _mapping(ac3.get("identities"), "A-C3 identities")
        data_version = str(identities.get("data_version", "")).strip()
        if not data_version:
            raise ValueError("A-C3 data_version is missing")
        if data.get("dataset_version") not in {None, "", data_version}:
            raise ValueError(
                "A-C3 dataset_version disagrees with identities.data_version"
            )
        if data.get("content_hashed") is not True:
            raise ValueError("A-C3 dataset evidence is not content-hashed")
        if self.config.mode == "real_local_evidence":
            if ac3.get("mode") != "real_local_dataset":
                raise ValueError("real A-C5 requires real_local_dataset A-C3 evidence")
            if ac3.get("accepted") is not True:
                raise ValueError("real A-C5 requires accepted=true A-C3 evidence")
            if ac3.get("real_dataset_attested") is not True:
                raise ValueError("real A-C5 requires real_dataset_attested=true")
            if data.get("content_verified") is not True:
                raise ValueError("real A-C5 requires content_verified=true")

        frozen = LocalAshareFrozenManifest.read_json(self.config.frozen_dataset_manifest)
        if frozen.dataset_version != data_version:
            raise ValueError("frozen dataset manifest version differs from A-C3")
        if not frozen.content_hashed:
            raise ValueError("A-C5 requires a content-hashed frozen dataset manifest")

        artifacts_raw = _mapping(ac3.get("artifacts"), "A-C3 artifacts")
        descriptors: list[dict[str, object]] = []
        package_sources: list[tuple[str, Path]] = []
        certification_descriptor: dict[str, object] | None = None
        for role, raw in sorted(artifacts_raw.items()):
            if raw is None:
                continue
            descriptor, path = _verify_recorded_artifact(str(role), raw)
            descriptors.append(descriptor)
            package_sources.append((f"evidence/ac3/{role}/{path.name}", path))
            if str(role) == "certification":
                certification_descriptor = descriptor

        terminal_state = str(ac3.get("terminal_state", "")).strip()
        if terminal_state == "NO_ROBUST_FACTOR_FAMILY":
            research_outcome = "NO_ROBUST_FACTOR_FAMILY"
            if identities.get("market_bar_series_id") is not None:
                raise ValueError("no-alpha A-C3 must not bind MarketBarSeries")
        elif not terminal_state:
            research_outcome = "POPULATED_STRATEGY"
            for key in (
                "program_result_id",
                "portfolio_validation_id",
                "strategy_series_id",
                "factor_series_id",
                "market_bar_series_id",
            ):
                if not str(identities.get(key, "")).strip():
                    raise ValueError(f"populated A-C3 is missing identity {key}")
        else:
            raise ValueError(f"unsupported A-C3 terminal_state: {terminal_state!r}")

        checks = _mapping(ac3.get("checks"), "A-C3 checks")
        for key in (
            "development_reserve_untouched",
            "robust_reserve_untouched",
            "a4_reserve_untouched",
        ):
            if checks.get(key) is not True:
                raise ValueError(f"A-C3 does not attest {key}")

        command_runs = _mapping(ac3.get("command_runs"), "A-C3 command_runs")
        certification = _mapping(
            command_runs.get("data.certify_local_ashare"),
            "A-C3 certification CommandRun",
        )
        if certification.get("ok") is not True:
            raise ValueError("A-C3 certification CommandRun is not successful")
        certification_run_id = str(certification.get("command_run_id", "")).strip()
        if not certification_run_id:
            raise ValueError("A-C3 certification CommandRun has no run identity")
        certification_ids = [
            str(value) for value in _sequence(certification.get("evidence_ids"))
        ]

        if certification_descriptor is None:
            outputs = _mapping(certification.get("outputs", {}), "certification outputs")
            output_value = str(
                outputs.get("output_path") or outputs.get("report_path") or ""
            ).strip()
            if not output_value:
                raise ValueError(
                    "A-C3 no-alpha evidence must expose the certification output path"
                )
            certification_path = Path(output_value).expanduser().resolve()
            certification_descriptor = _artifact_descriptor(
                "ac3:certification",
                certification_path,
            )
            descriptors.append(certification_descriptor)
            package_sources.append(
                (
                    f"evidence/ac3/certification/{certification_path.name}",
                    certification_path,
                )
            )

        core_drift = _historical_core_drift(
            self.config.repository_root,
            evidence_sha=ac3_sha,
            release_sha=release_sha,
        )
        if core_drift:
            raise ValueError(
                "historical core changed after accepted A-C3 evidence: "
                + ", ".join(core_drift)
            )

        evidence: dict[str, object] = {
            "acceptance_id": str(ac3.get("acceptance_id", "")),
            "git_sha": ac3_sha,
            "research_outcome": research_outcome,
            "data_version": data_version,
            "identities": dict(identities),
            "certification_command_run_id": certification_run_id,
            "certification_evidence_ids": certification_ids,
            "certification_artifact_sha256": certification_descriptor["sha256"],
            "certification_artifact_size_bytes": certification_descriptor["size_bytes"],
            "historical_core_drift": list(core_drift),
        }
        return evidence, descriptors, package_sources

    def run(self) -> HistoricalFreezeResult:
        root = self.config.repository_root
        release_sha = _resolve_release_sha(root, self.config.release_git_sha)
        if (
            self.config.mode == "real_local_evidence"
            and self.config.require_clean_tracked_worktree
            and not _tracked_worktree_clean(root)
        ):
            raise ValueError("real A-C5 freeze requires a clean tracked Git worktree")

        ac3 = _load_json(self.config.ac3_report, "A-C3 report")
        ac4 = _load_json(self.config.ac4_report, "A-C4 report")
        ac4_id, deferred = self._validate_ac4(ac4, release_sha)
        ac3_evidence, ac3_artifacts, package_sources = self._validate_ac3(
            ac3,
            release_sha,
        )

        environment_artifacts: list[dict[str, object]] = []
        for path in self.config.environment_files:
            logical_name = _repo_relative(root, path)
            environment_artifacts.append(
                _artifact_descriptor(
                    "environment",
                    path,
                    logical_name=logical_name,
                )
            )

        all_artifacts = [
            _artifact_descriptor(
                "dataset_manifest",
                self.config.frozen_dataset_manifest,
                logical_name="data/manifests/local_ashare_daily.json",
            ),
            _artifact_descriptor(
                "ac3_acceptance",
                self.config.ac3_report,
                logical_name="ashare_historical_acceptance_ac3.json",
            ),
            _artifact_descriptor(
                "ac4_compliance",
                self.config.ac4_report,
                logical_name="ashare_initial_requirement_compliance_ac4.json",
            ),
            _artifact_descriptor(
                "ac4_manifest",
                self.config.ac4_manifest,
                logical_name=(
                    "configs/acceptance/ashare_initial_requirement_compliance_ac4.toml"
                ),
            ),
            *ac3_artifacts,
            *environment_artifacts,
        ]

        summary = _mapping(ac4.get("summary"), "A-C4 summary")
        checks = {
            "release_git_sha_resolved": bool(release_sha),
            "ac3_contract_valid": ac3.get("contract_valid") is True,
            "ac3_real_acceptance_required": (
                self.config.mode != "real_local_evidence"
                or (
                    ac3.get("accepted") is True
                    and ac3.get("real_dataset_attested") is True
                )
            ),
            "ac3_historical_core_unchanged": not ac3_evidence[
                "historical_core_drift"
            ],
            "ac4_exact_replay": bool(ac4_id),
            "ac4_on_release_sha": (
                self.config.mode != "real_local_evidence"
                or str(ac4.get("git_sha", "")) == release_sha
            ),
            "ac4_has_no_partial": int(cast(Any, summary.get("PARTIAL", -1))) == 0,
            "deferred_capabilities_frozen": (
                deferred == HISTORICAL_V1_DEFERRED_CAPABILITIES
            ),
            "dataset_manifest_content_hashed": True,
            "historical_closure_did_not_consume_reserve": True,
        }
        contract_valid = all(checks.values())
        frozen = contract_valid and self.config.mode == "real_local_evidence"

        identity_material = {
            "schema_version": AC5_FREEZE_SCHEMA,
            "release_name": AC5_RELEASE_NAME,
            "release_git_sha": release_sha,
            "mode": self.config.mode,
            "ac3": ac3_evidence,
            "ac4_audit_id": ac4_id,
            "deferred_capabilities": list(deferred),
            "artifacts": [
                {
                    "role": item["role"],
                    "logical_name": item["logical_name"],
                    "sha256": item["sha256"],
                    "size_bytes": item["size_bytes"],
                }
                for item in all_artifacts
            ],
            "reserve": {
                "historical_closure_consumed": False,
                "promotion_implied": False,
            },
        }
        freeze_id = _digest(AC5_FREEZE_ID_PREFIX, identity_material)
        payload: dict[str, object] = {
            **identity_material,
            "freeze_id": freeze_id,
            "stage": "A-C5",
            "contract_valid": contract_valid,
            "frozen": frozen,
            "freeze_semantics": (
                "CI fixtures validate only the freeze contract. Historical v1.0 is "
                "frozen only from real accepted A-C3 evidence, an exact A-C4 replay "
                "on the release Git SHA, a content-hashed dataset manifest, verified "
                "source artifacts and zero historical-core drift after the accepted "
                "A-C3 revision."
            ),
            "checks": checks,
            "production_reserve": {
                "historical_closure_consumed": False,
                "promotion_eligible": False,
                "paper_enabled_by_freeze": False,
                "live_capital_enabled_by_freeze": False,
            },
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

        package_sources.extend(
            (
                (
                    "release/ac3/ashare_historical_acceptance_ac3.json",
                    self.config.ac3_report,
                ),
                (
                    "release/ac4/ashare_initial_requirement_compliance_ac4.json",
                    self.config.ac4_report,
                ),
                (
                    "release/ac4/ashare_initial_requirement_compliance_ac4.toml",
                    self.config.ac4_manifest,
                ),
                (
                    "release/data/local_ashare_daily_manifest.json",
                    self.config.frozen_dataset_manifest,
                ),
            )
        )
        for path in self.config.environment_files:
            package_sources.append(
                (f"release/environment/{_repo_relative(root, path)}", path)
            )
        package_sources.extend(
            (
                (
                    "release/freeze/finagent_ashare_historical_v1_freeze.json",
                    self.config.output_json,
                ),
                (
                    "release/freeze/finagent_ashare_historical_v1_freeze.md",
                    self.config.output_markdown,
                ),
            )
        )
        package_sha = self._build_package(self.config.output_package, package_sources)
        return HistoricalFreezeResult(
            payload=payload,
            json_path=self.config.output_json,
            markdown_path=self.config.output_markdown,
            package_path=self.config.output_package,
            package_sha256=package_sha,
        )

    @staticmethod
    def _markdown(payload: Mapping[str, object]) -> str:
        ac3 = _mapping(payload.get("ac3"), "freeze ac3")
        identities = _mapping(ac3.get("identities"), "freeze identities")
        deferred = tuple(
            str(value) for value in _sequence(payload.get("deferred_capabilities"))
        )
        lines = [
            "# FinAgent A-share Historical v1.0 Freeze",
            "",
            f"- Freeze ID: `{payload.get('freeze_id')}`",
            f"- Release Git SHA: `{payload.get('release_git_sha')}`",
            f"- Contract valid: `{str(bool(payload.get('contract_valid'))).lower()}`",
            f"- Frozen: `{str(bool(payload.get('frozen'))).lower()}`",
            f"- A-C3 acceptance: `{ac3.get('acceptance_id')}`",
            f"- A-C3 research outcome: `{ac3.get('research_outcome')}`",
            f"- A-C4 audit: `{payload.get('ac4_audit_id')}`",
            f"- Dataset version: `{ac3.get('data_version')}`",
            "",
            "## Evidence identities",
            "",
            f"- program_result_id: `{identities.get('program_result_id')}`",
            f"- portfolio_validation_id: `{identities.get('portfolio_validation_id')}`",
            f"- strategy_series_id: `{identities.get('strategy_series_id')}`",
            f"- factor_series_id: `{identities.get('factor_series_id')}`",
            f"- market_bar_series_id: `{identities.get('market_bar_series_id')}`",
            "",
            "## Deferred capabilities",
            "",
        ]
        lines.extend(f"- `{value}`" for value in deferred)
        lines.extend(
            (
                "",
                "## Boundary",
                "",
                "Historical v1.0 freeze does not consume the production reserve, "
                "imply promotion, enable PAPER, contact a broker, or authorize live capital.",
                "",
            )
        )
        return "\n".join(lines)

    @staticmethod
    def _build_package(
        target: Path,
        sources: Sequence[tuple[str, Path]],
    ) -> str:
        target.parent.mkdir(parents=True, exist_ok=True)
        unique: dict[str, Path] = {}
        for archive_name, path in sources:
            name = archive_name.replace("\\", "/").lstrip("/")
            if not name:
                raise ValueError(f"invalid A-C5 archive path: {archive_name!r}")
            if name in unique:
                if unique[name] == path:
                    continue
                raise ValueError(f"duplicate A-C5 archive path: {archive_name!r}")
            unique[name] = path
        with zipfile.ZipFile(
            target,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
        ) as archive:
            for archive_name in sorted(unique):
                path = unique[archive_name]
                if not path.is_file():
                    raise FileNotFoundError(path)
                info = zipfile.ZipInfo(
                    archive_name,
                    date_time=(1980, 1, 1, 0, 0, 0),
                )
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                archive.writestr(
                    info,
                    path.read_bytes(),
                    compress_type=zipfile.ZIP_DEFLATED,
                    compresslevel=9,
                )
        return _sha256(target)
