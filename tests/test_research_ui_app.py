from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.test_research_visualization import _report


AppTest = pytest.importorskip("streamlit.testing.v1").AppTest
ROOT = Path(__file__).resolve().parents[1]


def test_streamlit_app_starts_without_a_report(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FINAGENT_RESEARCH_REPORT", raising=False)
    monkeypatch.delenv("FINAGENT_FEATURE_STORE", raising=False)
    monkeypatch.delenv("FINAGENT_AGENT_TRACE_JSONL", raising=False)
    app = AppTest.from_file(ROOT / "apps" / "research_ui.py", default_timeout=15)
    app.run()
    assert not app.exception
    assert app.title[0].value == "FinAgent Research UI"
    assert "read-only" in app.sidebar.caption[0].value.lower()


def test_streamlit_app_renders_the_default_research_page(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = tmp_path / "report.json"
    report.write_text(json.dumps(_report()), encoding="utf-8")
    monkeypatch.setenv("FINAGENT_RESEARCH_REPORT", str(report))
    monkeypatch.setenv("FINAGENT_FEATURE_STORE", str(tmp_path / "missing.sqlite"))
    monkeypatch.setenv("FINAGENT_AGENT_TRACE_JSONL", str(tmp_path / "missing.jsonl"))
    app = AppTest.from_file(ROOT / "apps" / "research_ui.py", default_timeout=20)
    app.run()
    assert not app.exception
    assert any(title.value == "Research Overview" for title in app.title)
    metric_labels = {metric.label for metric in app.metric}
    assert {"System", "Research", "Candidates", "Reserve"}.issubset(metric_labels)
