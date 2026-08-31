from __future__ import annotations

import zipfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from finagent.backtest import StrategyDecisionSeriesProjection
from finagent.research import FactorSeriesProjection
from finagent.runtime import ashare_historical_v1_freeze as base
from finagent.runtime.ashare_historical_acceptance_terminal import is_no_alpha_terminal

# A-C3's recorded git_sha is the evidence-production baseline.  A-C4/A-C5 and
# acceptance-only compatibility patches may legitimately be newer without changing
# the already materialized A2.6/A4 economics.  These two paths are explicitly
# release/verifier-layer code and therefore do not invalidate the historical
# evidence baseline by themselves.
AC5_POST_AC3_NON_ECONOMIC_PATHS = frozenset(
    {
        "src/finagent/runtime/ashare_historical_acceptance_terminal.py",
        "scripts/run_workbench_control.py",
    }
)

AC5_EVIDENCE_CORE_PATHS = tuple(
    path
    for path in base.HISTORICAL_CORE_PATHS
    if path not in AC5_POST_AC3_NON_ECONOMIC_PATHS
)


def _evidence_core_drift(
    repository_root: Path,
    *,
    evidence_sha: str,
    release_sha: str,
) -> tuple[str, ...]:
    if evidence_sha == release_sha:
        return ()
    result = base._git(
        repository_root,
        "diff",
        "--name-only",
        f"{evidence_sha}..{release_sha}",
        "--",
        *AC5_EVIDENCE_CORE_PATHS,
    )
    return tuple(line.strip() for line in result.stdout.splitlines() if line.strip())


class AshareHistoricalV1LineageFreezer(base.AshareHistoricalV1Freezer):
    """A-C5 freezer with explicit evidence-SHA versus verifier-SHA lineage.

    The original A-C3 ``git_sha`` remains the immutable evidence-production
    baseline.  The final release SHA is separately recorded as the revision whose
    A-C5 verifier replays the A-C3 identity/artifacts and, for the no-alpha terminal,
    independently revalidates the terminal semantics.
    """

    def _validate_ac3(
        self,
        ac3: Mapping[str, Any],
        release_sha: str,
    ) -> tuple[dict[str, object], list[dict[str, object]], list[tuple[str, Path]]]:
        if ac3.get("schema_version") != base.AC3_ACCEPTANCE_SCHEMA:
            raise ValueError("A-C3 report schema mismatch")
        if ac3.get("contract_valid") is not True:
            raise ValueError("A-C3 contract is not valid")
        ac3_sha = base._full_sha(ac3.get("git_sha"), "A-C3 evidence git_sha")
        if not base._is_ancestor(self.config.repository_root, ac3_sha, release_sha):
            raise ValueError("A-C3 evidence Git SHA is not an ancestor of release Git SHA")
        if str(ac3.get("acceptance_id", "")) != base.recompute_ac3_acceptance_id(ac3):
            raise ValueError("A-C3 acceptance_id does not recompute exactly")

        data = base._mapping(ac3.get("data"), "A-C3 data")
        identities = base._mapping(ac3.get("identities"), "A-C3 identities")
        data_version = str(identities.get("data_version", "")).strip()
        if not data_version:
            raise ValueError("A-C3 data_version is missing")
        if data.get("dataset_version") not in {None, "", data_version}:
            raise ValueError("A-C3 dataset_version disagrees with identities.data_version")
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

        frozen = base.LocalAshareFrozenManifest.read_json(
            self.config.frozen_dataset_manifest
        )
        if frozen.dataset_version != data_version:
            raise ValueError("frozen dataset manifest version differs from A-C3")
        if not frozen.content_hashed:
            raise ValueError("A-C5 requires a content-hashed frozen dataset manifest")

        terminal_state = str(ac3.get("terminal_state", "")).strip()
        required_artifacts: tuple[str, ...]
        if terminal_state == "NO_ROBUST_FACTOR_FAMILY":
            research_outcome = "NO_ROBUST_FACTOR_FAMILY"
            if identities.get("market_bar_series_id") is not None:
                raise ValueError("no-alpha A-C3 must not bind MarketBarSeries")
            required_artifacts = base.AC5_NO_ALPHA_AC3_ARTIFACTS
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
            required_artifacts = base.AC5_POPULATED_AC3_ARTIFACTS
        else:
            raise ValueError(f"unsupported A-C3 terminal_state: {terminal_state!r}")

        artifacts_raw = base._mapping(ac3.get("artifacts"), "A-C3 artifacts")
        missing_artifacts = [
            role for role in required_artifacts if artifacts_raw.get(role) is None
        ]
        if missing_artifacts:
            raise ValueError(
                "A-C3 required release artifacts are missing: "
                + ", ".join(missing_artifacts)
            )
        if terminal_state == "NO_ROBUST_FACTOR_FAMILY" and artifacts_raw.get(
            "market_bar_manifest"
        ) is not None:
            raise ValueError("no-alpha A-C3 must keep market_bar_manifest absent")

        descriptors: list[dict[str, object]] = []
        package_sources: list[tuple[str, Path]] = []
        verified_paths: dict[str, Path] = {}
        certification_descriptor: dict[str, object] | None = None
        review_path: Path | None = None
        for role, raw in sorted(artifacts_raw.items()):
            if raw is None:
                continue
            descriptor, path = base._verify_recorded_artifact(
                str(role),
                raw,
                repository_root=self.config.repository_root,
            )
            verified_paths[str(role)] = path
            descriptors.append(descriptor)
            package_sources.append((f"evidence/ac3/{role}/{path.name}", path))
            if str(role) == "certification":
                certification_descriptor = descriptor
            if str(role) == "review_bundle":
                review_path = path
        if review_path is None or not zipfile.is_zipfile(review_path):
            raise ValueError("A-C3 review_bundle is not a valid ZIP artifact")

        # The final release verifier independently confirms the exact no-alpha
        # terminal instead of trusting only the older A-C3 verifier code.  This is
        # what makes it safe to separate evidence_git_sha from reverification_git_sha.
        no_alpha_reverified = True
        if terminal_state == "NO_ROBUST_FACTOR_FAMILY":
            robust = base._load_json(verified_paths["robust"], "A-C3 robust report")
            a4 = base._load_json(verified_paths["a4"], "A-C3 A4 report")
            if not is_no_alpha_terminal(robust, a4):
                raise ValueError(
                    "current A-C5 verifier does not confirm the reviewed no-alpha terminal"
                )
            if verified_paths["a4_ledger"].stat().st_size != 0:
                raise ValueError("no-alpha A-C3 requires an empty A4 ledger")
            strategy = StrategyDecisionSeriesProjection(
                verified_paths["strategy_manifest"]
            ).manifest
            factors = FactorSeriesProjection(verified_paths["factor_manifest"]).manifest
            if not (
                strategy.row_count == 0
                and strategy.row_session_count == 0
                and strategy.asset_count == 0
                and strategy.start_date is None
                and strategy.end_date is None
            ):
                raise ValueError("no-alpha StrategyDecisionSeries is not explicitly empty")
            if strategy.portfolio_validation_id != str(
                identities.get("portfolio_validation_id", "")
            ):
                raise ValueError("no-alpha StrategyDecisionSeries/A4 identity mismatch")
            if strategy.source_program_result_id != str(
                identities.get("program_result_id", "")
            ):
                raise ValueError("no-alpha StrategyDecisionSeries/program identity mismatch")
            if strategy.data_version != data_version:
                raise ValueError("no-alpha StrategyDecisionSeries data_version mismatch")
            if factors.row_count <= 0:
                raise ValueError("no-alpha FactorSeries must remain materialized")
            if factors.program_result_id != str(identities.get("program_result_id", "")):
                raise ValueError("no-alpha FactorSeries/program identity mismatch")
            if factors.data_version != data_version:
                raise ValueError("no-alpha FactorSeries data_version mismatch")

        checks = base._mapping(ac3.get("checks"), "A-C3 checks")
        for key in (
            "development_reserve_untouched",
            "robust_reserve_untouched",
            "a4_reserve_untouched",
        ):
            if checks.get(key) is not True:
                raise ValueError(f"A-C3 does not attest {key}")

        command_runs = base._mapping(ac3.get("command_runs"), "A-C3 command_runs")
        command_run_ids: dict[str, str] = {}
        for command_id in base.AC3_REQUIRED_COMMANDS:
            record = base._mapping(
                command_runs.get(command_id),
                f"A-C3 CommandRun {command_id}",
            )
            if record.get("ok") is not True:
                raise ValueError(f"A-C3 CommandRun is not successful: {command_id}")
            run_id = str(record.get("command_run_id", "")).strip()
            if not run_id:
                raise ValueError(f"A-C3 CommandRun has no identity: {command_id}")
            command_run_ids[command_id] = run_id

        certification = base._mapping(
            command_runs.get("data.certify_local_ashare"),
            "A-C3 certification CommandRun",
        )
        certification_ids = [
            str(value) for value in base._sequence(certification.get("evidence_ids"))
        ]
        if certification_descriptor is None:
            outputs = base._mapping(
                certification.get("outputs", {}), "certification outputs"
            )
            output_value = str(
                outputs.get("output_path") or outputs.get("report_path") or ""
            ).strip()
            if not output_value:
                raise ValueError(
                    "A-C3 no-alpha evidence must expose the certification output path"
                )
            certification_path = base._resolve(
                self.config.repository_root, output_value
            )
            certification_descriptor = base._artifact_descriptor(
                "ac3:certification", certification_path
            )
            descriptors.append(certification_descriptor)
            package_sources.append(
                (
                    f"evidence/ac3/certification/{certification_path.name}",
                    certification_path,
                )
            )

        core_drift = _evidence_core_drift(
            self.config.repository_root,
            evidence_sha=ac3_sha,
            release_sha=release_sha,
        )
        if core_drift:
            raise ValueError(
                "historical evidence core changed after accepted A-C3 evidence: "
                + ", ".join(core_drift)
            )

        evidence: dict[str, object] = {
            "acceptance_id": str(ac3.get("acceptance_id", "")),
            # Backward-compatible alias retained for existing consumers.
            "git_sha": ac3_sha,
            "evidence_git_sha": ac3_sha,
            "reverification_git_sha": release_sha,
            "research_outcome": research_outcome,
            "data_version": data_version,
            "identities": dict(identities),
            "command_run_ids": command_run_ids,
            "certification_command_run_id": command_run_ids[
                "data.certify_local_ashare"
            ],
            "certification_evidence_ids": certification_ids,
            "certification_artifact_sha256": certification_descriptor["sha256"],
            "certification_artifact_size_bytes": certification_descriptor["size_bytes"],
            "historical_core_drift": list(core_drift),
            "no_alpha_terminal_reverified": no_alpha_reverified,
            "post_ac3_non_economic_paths": sorted(AC5_POST_AC3_NON_ECONOMIC_PATHS),
        }
        return evidence, descriptors, package_sources
