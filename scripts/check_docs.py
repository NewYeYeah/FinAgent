#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
STATUS = DOCS / "status.toml"
PLAN = DOCS / "development" / "current-plan.md"
STAGES = DOCS / "development" / "stages"
AGENT_ENTRY = ROOT / "AGENTS.md"
SKILL = ROOT / "skills" / "finagent-project" / "SKILL.md"

REQUIRED_DOCS = (
    DOCS / "README.md",
    DOCS / "development" / "history.md",
    DOCS / "development" / "backlog.md",
    DOCS / "architecture" / "overview.md",
    DOCS / "architecture" / "decisions.md",
    DOCS / "testing" / "strategy.md",
    DOCS / "guides" / "getting-started.md",
    DOCS / "guides" / "data.md",
    DOCS / "guides" / "research-workflow.md",
    DOCS / "guides" / "workbench.md",
    DOCS / "guides" / "mt5-paper.md",
)

REQUIRED_STAGE_FILES = {
    "r3-close.md",
    "r4-agent-adaptive.md",
    "r5-independent-confirmation.md",
    "workbench-2.md",
    "paper-trading.md",
    "live-capital.md",
}

ALLOWED_GUIDES = {
    "getting-started.md",
    "data.md",
    "research-workflow.md",
    "workbench.md",
    "mt5-paper.md",
}

FORBIDDEN_DEVELOPMENT_PATTERNS = (
    re.compile(r"^current-development-plan-v.*\.md$", re.I),
    re.compile(r"^roadmap.*\.md$", re.I),
    re.compile(r"^changelog.*\.md$", re.I),
)

LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def fail(errors: list[str], message: str) -> None:
    errors.append(message)


def check_required_files(errors: list[str]) -> None:
    for path in (AGENT_ENTRY, STATUS, PLAN, SKILL, *REQUIRED_DOCS):
        if not path.is_file():
            fail(errors, f"missing required documentation file: {path.relative_to(ROOT)}")
    if not STAGES.is_dir():
        fail(errors, "missing docs/development/stages")
        return
    observed = {path.name for path in STAGES.glob("*.md")}
    missing = REQUIRED_STAGE_FILES - observed
    extra = observed - REQUIRED_STAGE_FILES
    for name in sorted(missing):
        fail(errors, f"missing required stage plan: docs/development/stages/{name}")
    for name in sorted(extra):
        fail(errors, f"unexpected active stage plan: docs/development/stages/{name}")


def check_status(errors: list[str]) -> dict[str, object]:
    if not STATUS.is_file():
        return {}
    try:
        with STATUS.open("rb") as handle:
            raw = tomllib.load(handle)
    except Exception as exc:  # pragma: no cover
        fail(errors, f"docs/status.toml is invalid TOML: {exc}")
        return {}

    required = (
        "schema_version",
        "planning_revision",
        "planning_document",
        "current_stage",
        "current_stage_status",
        "next_stage",
        "stage_plan",
        "last_updated",
    )
    for key in required:
        if not str(raw.get(key, "")).strip():
            fail(errors, f"docs/status.toml missing/non-empty {key}")

    if raw.get("planning_document") != "docs/development/current-plan.md":
        fail(errors, "planning_document must be docs/development/current-plan.md")

    stage_plan = str(raw.get("stage_plan", "")).strip()
    if stage_plan:
        path = ROOT / stage_plan
        if not path.is_file():
            fail(errors, f"stage_plan does not exist: {stage_plan}")
        try:
            path.relative_to(STAGES)
        except ValueError:
            fail(errors, "stage_plan must live under docs/development/stages")

    doc = raw.get("documentation")
    if not isinstance(doc, dict):
        fail(errors, "docs/status.toml requires [documentation]")
    else:
        expected = {
            "active_plan_count": 1,
            "agent_entrypoint": "AGENTS.md",
            "stage_plan_directory": "docs/development/stages",
            "history_document": "docs/development/history.md",
            "backlog_document": "docs/development/backlog.md",
            "architecture_document": "docs/architecture/overview.md",
            "decisions_document": "docs/architecture/decisions.md",
            "testing_document": "docs/testing/strategy.md",
            "onboarding_skill": "skills/finagent-project/SKILL.md",
        }
        for key, value in expected.items():
            if doc.get(key) != value:
                fail(errors, f"documentation.{key} must equal {value!r}")

    return raw


def check_compactness(errors: list[str]) -> None:
    limits = {
        STATUS: 180,
        AGENT_ENTRY: 260,
        PLAN: 420,
        DOCS / "development" / "history.md": 420,
        DOCS / "development" / "backlog.md": 420,
    }
    for path in STAGES.glob("*.md") if STAGES.is_dir() else ():
        limits[path] = 520
    for path, limit in limits.items():
        if not path.is_file():
            continue
        count = len(path.read_text(encoding="utf-8").splitlines())
        if count > limit:
            fail(errors, f"documentation sprawl: {path.relative_to(ROOT)} has {count} lines > {limit}")


def check_structure(errors: list[str]) -> None:
    development = DOCS / "development"
    if len(list(development.glob("current-plan.md"))) != 1:
        fail(errors, "expected exactly one docs/development/current-plan.md")

    for path in development.iterdir() if development.is_dir() else ():
        if not path.is_file():
            continue
        for pattern in FORBIDDEN_DEVELOPMENT_PATTERNS:
            if pattern.match(path.name):
                fail(errors, f"forbidden active development document: {path.relative_to(ROOT)}")

    guides = DOCS / "guides"
    observed_guides = {path.name for path in guides.glob("*.md")} if guides.is_dir() else set()
    for name in sorted(observed_guides - ALLOWED_GUIDES):
        fail(errors, f"unexpected active guide: docs/guides/{name}")
    for name in sorted(ALLOWED_GUIDES - observed_guides):
        fail(errors, f"missing active guide: docs/guides/{name}")


def check_stage_contracts(errors: list[str], status: dict[str, object]) -> None:
    current_stage = str(status.get("current_stage", "")).strip()
    if PLAN.is_file():
        text = PLAN.read_text(encoding="utf-8")
        if current_stage and current_stage not in text:
            fail(errors, f"current stage {current_stage!r} is not described in current-plan.md")
        for name in sorted(REQUIRED_STAGE_FILES):
            target = f"stages/{name}"
            if target not in text:
                fail(errors, f"current-plan.md must link {target}")

    for path in STAGES.glob("*.md") if STAGES.is_dir() else ():
        text = path.read_text(encoding="utf-8")
        for heading in ("## Goal", "## Deliverables", "## Non-goals", "## Exit gate"):
            if heading not in text:
                fail(errors, f"{path.relative_to(ROOT)} missing required heading {heading!r}")


def resolve_markdown_link(source: Path, target: str) -> Path | None:
    target = target.strip().split("#", 1)[0]
    if not target or target.startswith(("http://", "https://", "mailto:", "#")):
        return None
    return (source.parent / target).resolve()


def check_links(errors: list[str]) -> None:
    sources = [ROOT / "README.md", AGENT_ENTRY, SKILL, *DOCS.rglob("*.md")]
    for source in sources:
        if not source.is_file():
            continue
        for target in LINK_RE.findall(source.read_text(encoding="utf-8")):
            resolved = resolve_markdown_link(source, target)
            if resolved is not None and not resolved.exists():
                fail(errors, f"broken relative link in {source.relative_to(ROOT)}: {target}")


def check_entrypoints(errors: list[str]) -> None:
    root_readme = ROOT / "README.md"
    root_text = root_readme.read_text(encoding="utf-8") if root_readme.is_file() else ""
    for target in ("AGENTS.md", "docs/status.toml", "docs/development/current-plan.md"):
        if target not in root_text:
            fail(errors, f"README.md must link {target}")

    docs_index = DOCS / "README.md"
    docs_text = docs_index.read_text(encoding="utf-8") if docs_index.is_file() else ""
    if "../AGENTS.md" not in docs_text:
        fail(errors, "docs/README.md must link ../AGENTS.md")

    skill_text = SKILL.read_text(encoding="utf-8") if SKILL.is_file() else ""
    if "../../AGENTS.md" not in skill_text:
        fail(errors, "FinAgent project Skill must delegate to ../../AGENTS.md")


def check_release_ref(errors: list[str], status: dict[str, object]) -> None:
    release = status.get("release")
    if not isinstance(release, dict):
        return
    ashare = release.get("ashare_historical_v1")
    if not isinstance(ashare, dict):
        return
    path = str(ashare.get("release_document", "")).strip()
    if path and not (ROOT / path).is_file():
        fail(errors, f"release_document does not exist: {path}")
    if ashare.get("status") == "accepted":
        for key in ("tag", "tag_target", "freeze_id", "smoke_id", "research_outcome", "accepted_at"):
            if not str(ashare.get(key, "")).strip():
                fail(errors, f"accepted A-share release missing {key}")
        target = str(ashare.get("tag_target", "")).strip().lower()
        if target and not SHA_RE.fullmatch(target):
            fail(errors, "accepted A-share release tag_target must be a 40-char Git SHA")
        if ashare.get("contract_valid") is not True:
            fail(errors, "accepted A-share release must record contract_valid=true")
        if ashare.get("browser_status") != "passed":
            fail(errors, "accepted A-share release must record browser_status=passed")
        if ashare.get("production_reserve_consumed") is not False:
            fail(errors, "accepted A-share release must record reserve non-consumption")


def main() -> int:
    errors: list[str] = []
    check_required_files(errors)
    status = check_status(errors)
    check_compactness(errors)
    check_structure(errors)
    check_stage_contracts(errors, status)
    check_entrypoints(errors)
    check_release_ref(errors, status)
    check_links(errors)

    if errors:
        print("Documentation governance check failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print("Documentation governance check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
