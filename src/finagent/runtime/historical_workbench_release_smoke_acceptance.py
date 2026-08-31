from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from . import historical_workbench_release_smoke as base


# The base denominator intentionally protects the broad ``workspace/src`` tree. The
# release-acceptance layer narrows that Git pathspec by excluding test-only sources:
# they can be hardened after A-C5 without changing the frozen browser product. Runtime
# source, package/build configuration and every non-test file remain fail-closed.
_WORKBENCH_PRODUCT_TEST_EXCLUDES = (
    ":(exclude,glob)workspace/src/**/*.test.ts",
    ":(exclude,glob)workspace/src/**/*.test.tsx",
    ":(exclude,glob)workspace/src/test/**",
)
_WORKBENCH_PRODUCT_PATHS = (
    *base.WORKBENCH_PRODUCT_PATHS,
    *_WORKBENCH_PRODUCT_TEST_EXCLUDES,
)
# The base module's tuple is inferred by mypy as a fixed-length literal tuple. Use an
# explicit policy injection instead of assigning a longer tuple through that narrow
# static type; all runtime consumers still read the same module-level denominator.
setattr(base, "WORKBENCH_PRODUCT_PATHS", _WORKBENCH_PRODUCT_PATHS)


def _protected_worktree_changes(repository_root: Path) -> tuple[str, ...]:
    """Return tracked/staged/untracked changes under the frozen Workbench product.

    The real browser smoke builds from the working tree rather than a detached Git
    object. Commit-to-commit drift checks therefore are not sufficient: a local
    package.json edit, source patch or staged file could otherwise be rendered while
    the smoke still records the clean HEAD SHA. Only the frozen runnable product
    denominator is inspected; reports, node_modules, dist, unit-test sources and
    HW-1.0-RS verifier/test files remain outside this guard.
    """

    output: set[str] = set()
    commands = (
        ("diff", "--name-only", "--"),
        ("diff", "--cached", "--name-only", "--"),
        ("ls-files", "--others", "--exclude-standard", "--"),
    )
    for prefix in commands:
        result = base._git(
            repository_root,
            *prefix,
            *base.WORKBENCH_PRODUCT_PATHS,
        )
        output.update(
            line.strip().replace("\\", "/")
            for line in result.stdout.splitlines()
            if line.strip()
        )
    return tuple(sorted(output))


class HistoricalWorkbenchReleaseSmoke(base.HistoricalWorkbenchReleaseSmoke):
    """HW-1.0-RS acceptance policy with a mandatory real browser pass.

    Backend-only execution is useful for diagnosis, but it cannot accept the real
    frozen Historical Workbench product. CI fixtures remain contract-only and can
    never claim real acceptance.
    """

    def prepare(self) -> base.HistoricalWorkbenchReleaseSmokePrepared:
        if self.config.mode == "real_frozen_release":
            changes = _protected_worktree_changes(self.config.repository_root)
            if changes:
                raise ValueError(
                    "real HW-1.0-RS requires clean protected Workbench product paths; "
                    "uncommitted changes: " + ", ".join(changes)
                )
        return super().prepare()

    def finalize(
        self,
        prepared: base.HistoricalWorkbenchReleaseSmokePrepared,
        *,
        browser_status: base.BrowserSmokeStatus,
        browser_detail: str = "",
    ) -> base.HistoricalWorkbenchReleaseSmokeResult:
        if browser_status not in {"passed", "failed", "not_run"}:
            raise ValueError(f"unsupported browser smoke status: {browser_status}")

        payload_base = dict(prepared.payload_base)
        contract_valid = bool(payload_base.get("contract_valid"))
        browser_required = self.config.mode == "real_frozen_release"
        browser_ok = (
            browser_status == "passed"
            if browser_required
            else browser_status != "failed"
        )
        accepted = (
            contract_valid
            and self.config.mode == "real_frozen_release"
            and browser_status == "passed"
        )
        identity_material = {
            "schema_version": base.HISTORICAL_WORKBENCH_RELEASE_SMOKE_SCHEMA,
            "freeze_id": payload_base.get("freeze_id"),
            "freeze_release_git_sha": payload_base.get("freeze_release_git_sha"),
            "smoke_git_sha": payload_base.get("smoke_git_sha"),
            "research_outcome": payload_base.get("research_outcome"),
            "identities": payload_base.get("identities"),
            "checks": payload_base.get("checks"),
            "browser_status": browser_status,
        }
        payload: dict[str, object] = {
            **payload_base,
            "smoke_id": base._digest(
                base.HISTORICAL_WORKBENCH_RELEASE_SMOKE_ID_PREFIX,
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
                "a clean protected Workbench working tree, zero committed Workbench "
                "product drift and a passing production-build Playwright smoke over "
                "the locally verified A-C3 evidence. Test-only Workbench sources are "
                "outside the frozen product denominator. Backend-only execution is "
                "diagnostic and cannot accept the real product."
            ),
        }
        if browser_required and not browser_ok:
            payload["acceptance_blocker"] = "REAL_BROWSER_SMOKE_NOT_PASSED"

        self.config.output_json.parent.mkdir(parents=True, exist_ok=True)
        self.config.output_json.write_text(
            base.json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        self.config.output_markdown.write_text(
            self._markdown(payload),
            encoding="utf-8",
        )
        return base.HistoricalWorkbenchReleaseSmokeResult(
            payload=payload,
            json_path=self.config.output_json,
            markdown_path=self.config.output_markdown,
        )

    @staticmethod
    def _markdown(payload: Mapping[str, object]) -> str:
        return base.HistoricalWorkbenchReleaseSmoke._markdown(payload)
