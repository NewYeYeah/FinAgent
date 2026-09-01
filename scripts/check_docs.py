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
ONBOARDING_GUIDE = DOCS / "guides" / "project-onboarding.md"
ONBOARDING_SKILL = ROOT / "skills" / "finagent-project" / "SKILL.md"

FORBIDDEN_DEVELOPMENT_PATTERNS = (
    re.compile(r"^current-development-plan-v.*\.md$", re.I),
    re.compile(r"^roadmap.*\.md$", re.I),
    re.compile(r"^changelog-.+\.md$", re.I),
)

LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def fail(errors: list[str], message: str) -> None:
    errors.append(message)


def check_status(errors: list[str]) -> dict[str, object]:
    if not STATUS.is_file():
        fail(errors, "missing docs/status.toml")
        return {}
    try:
        with STATUS.open("rb") as handle:
            raw = tomllib.load(handle)
    except Exception as exc:  # pragma: no cover - diagnostic path
        fail(errors, f"docs/status.toml is invalid TOML: {exc}")
        return {}
    required = (
        "schema_version",
        "planning_revision",
        "planning_document",
        "current_stage",
        "current_stage_status",
        "next_stage",
    )
    for key in required:
        if not str(raw.get(key, "")).strip():
            fail(errors, f"docs/status.toml missing/non-empty {key}")
    if raw.get("planning_document") != "docs/development/current-plan.md":
        fail(errors, "planning_document must be docs/development/current-plan.md")
    doc = raw.get("documentation")
    if not isinstance(doc, dict) or doc.get("active_plan_count") != 1:
        fail(errors, "documentation.active_plan_count must equal 1")
    if isinstance(doc, dict):
        if doc.get("onboarding_guide") != "docs/guides/project-onboarding.md":
            fail(errors, "documentation.onboarding_guide must point to the canonical onboarding guide")
        if doc.get("onboarding_skill") != "skills/finagent-project/SKILL.md":
            fail(errors, "documentation.onboarding_skill must point to the canonical project skill")
    return raw


def check_plan(errors: list[str], status: dict[str, object]) -> None:
    if not PLAN.is_file():
        fail(errors, "missing docs/development/current-plan.md")
        return
    text = PLAN.read_text(encoding="utf-8")
    stage = str(status.get("current_stage", "")).strip()
    if stage and stage not in text:
        fail(errors, f"current stage {stage!r} is not described in current-plan.md")


def check_active_tree(errors: list[str]) -> None:
    development = DOCS / "development"
    active_plans = list(development.glob("current-plan.md"))
    if len(active_plans) != 1:
        fail(errors, f"expected exactly one current-plan.md, found {len(active_plans)}")
    for path in development.iterdir():
        if not path.is_file():
            continue
        for pattern in FORBIDDEN_DEVELOPMENT_PATTERNS:
            if pattern.match(path.name):
                fail(errors, f"forbidden active development document: {path.relative_to(ROOT)}")


def check_onboarding(errors: list[str]) -> None:
    if not ONBOARDING_GUIDE.is_file():
        fail(errors, "missing docs/guides/project-onboarding.md")
    if not ONBOARDING_SKILL.is_file():
        fail(errors, "missing skills/finagent-project/SKILL.md")
    docs_index = DOCS / "README.md"
    text = docs_index.read_text(encoding="utf-8") if docs_index.is_file() else ""
    if "guides/project-onboarding.md" not in text:
        fail(errors, "docs/README.md must link the onboarding guide")
    if "../skills/finagent-project/SKILL.md" not in text:
        fail(errors, "docs/README.md must link the FinAgent project skill")


def check_readme(errors: list[str]) -> None:
    path = ROOT / "README.md"
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    forbidden = ("current development milestone is", "current milestone:", "current_stage =")
    lower = text.lower()
    for value in forbidden:
        if value in lower:
            fail(errors, f"README maintains independent current-stage text: {value!r}")
    if "docs/status.toml" not in text:
        fail(errors, "README must link docs/status.toml")
    if "skills/finagent-project/SKILL.md" not in text:
        fail(errors, "README must link the FinAgent project skill")


def resolve_markdown_link(source: Path, target: str) -> Path | None:
    target = target.strip().split("#", 1)[0]
    if not target or target.startswith(("http://", "https://", "mailto:", "#")):
        return None
    return (source.parent / target).resolve()


def check_links(errors: list[str]) -> None:
    sources = [ROOT / "README.md", *DOCS.rglob("*.md"), ONBOARDING_SKILL]
    for source in sources:
        if not source.is_file():
            continue
        for target in LINK_RE.findall(source.read_text(encoding="utf-8")):
            resolved = resolve_markdown_link(source, target)
            if resolved is not None and not resolved.exists():
                fail(errors, f"broken relative link in {source.relative_to(ROOT)}: {target}")


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
        required = (
            "tag",
            "tag_target",
            "freeze_id",
            "smoke_id",
            "research_outcome",
            "accepted_at",
        )
        for key in required:
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
    status = check_status(errors)
    check_plan(errors, status)
    check_active_tree(errors)
    check_onboarding(errors)
    check_readme(errors)
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
