from __future__ import annotations

import json
import math
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from finagent.research.factor_series import (
    FACTOR_SERIES_MANIFEST_SCHEMA,
    FactorSeriesManifest,
    FactorSeriesProjection,
)
from tests.test_ashare_robust_research_a26 import (
    test_a2p6_cli_runs_deterministic_walk_forward_and_exact_replay as _prepare_a26,
)


ROOT = Path(__file__).resolve().parents[1]


def _run_v41(
    *,
    config: Path,
    report: Path,
    manifest: Path,
    data: Path,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "materialize_factor_series.py"),
            str(config),
            "--a2p6-report",
            str(report),
            "--manifest",
            str(manifest),
            "--data",
            str(data),
            "--rolling-window",
            "20",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture(scope="module")
def v41_evidence(tmp_path_factory: pytest.TempPathFactory) -> dict[str, object]:
    root = tmp_path_factory.mktemp("v41-evidence")
    _prepare_a26(root)
    report = root / "robust.json"
    config = root / "a2p6.toml"
    report_before = report.read_bytes()
    source = json.loads(report.read_text(encoding="utf-8"))
    manifest_path = root / "robust.factor-series.json"
    data_path = root / "robust.factor-series.parquet"
    result = _run_v41(
        config=config,
        report=report,
        manifest=manifest_path,
        data=data_path,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert report.read_bytes() == report_before
    return {
        "root": root,
        "report": report,
        "config": config,
        "report_before": report_before,
        "source": source,
        "manifest": manifest_path,
        "data": data_path,
    }


def test_v41_materializes_reconciled_factor_series_and_bounded_projection(
    v41_evidence: dict[str, object],
) -> None:
    root = Path(v41_evidence["root"])
    report = Path(v41_evidence["report"])
    config = Path(v41_evidence["config"])
    report_before = bytes(v41_evidence["report_before"])
    source = v41_evidence["source"]
    assert isinstance(source, dict)
    manifest_path = Path(v41_evidence["manifest"])

    manifest = FactorSeriesManifest.read_json(manifest_path)
    assert manifest.schema_version == FACTOR_SERIES_MANIFEST_SCHEMA
    assert manifest.authority == "authoritative"
    assert manifest.program_result_id == source["program_result_id"]
    assert manifest.program_spec_id == source["program_spec"]["spec_id"]
    assert manifest.walk_forward_report_id == source["walk_forward_report"]["report_id"]
    assert manifest.gate_report_id == source["gate_report"]["gate_report_id"]
    assert manifest.selection_id == source["frozen_selection"]["selection_id"]
    assert manifest.factor_count == len(source["candidate_denominator"]) == 3
    assert manifest.fold_count == 2
    assert manifest.quantiles == 3
    assert manifest.rolling_window == 20
    assert manifest.row_count > 1000
    assert manifest.session_count > 400
    assert set(manifest.selected_feature_digests).issubset(
        manifest.candidate_feature_digests
    )

    projection = FactorSeriesProjection(manifest_path)
    first_factor = manifest.candidate_feature_digests[0]
    primary = manifest.primary_label

    rank_ic = projection.query(
        feature_digest=first_factor,
        series_kind="ic",
        metric="rank_ic",
        label_name=primary,
        limit=500,
    )
    assert rank_ic["total"] > 100
    assert rank_ic["items"]
    assert all(item["authority"] == "authoritative" for item in rank_ic["items"])
    assert all(math.isfinite(float(item["value"])) for item in rank_ic["items"])

    rolling = projection.query(
        feature_digest=first_factor,
        series_kind="ic",
        metric="rolling_rank_ic",
        label_name=primary,
        limit=500,
    )
    assert rolling["total"] > 0
    assert all(item["authority"] == "derived" for item in rolling["items"])
    assert all(int(item["window_count"]) == 20 for item in rolling["items"])

    decay_label = manifest.decay_labels[0]
    decay = projection.query(
        feature_digest=first_factor,
        series_kind="ic",
        metric="rank_ic",
        label_name=decay_label,
        limit=500,
    )
    assert decay["total"] > 0

    quantile = projection.query(
        feature_digest=first_factor,
        series_kind="quantile",
        metric="return",
        label_name=primary,
        quantile=3,
        limit=500,
    )
    assert quantile["total"] > 0
    assert all(int(item["quantile"]) == 3 for item in quantile["items"])

    nav = projection.query(
        feature_digest=first_factor,
        series_kind="long_short",
        metric="nav",
        label_name=primary,
        limit=500,
    )
    assert nav["total"] > 0
    assert all(item["authority"] == "derived" for item in nav["items"])

    turnover = projection.query(
        feature_digest=first_factor,
        series_kind="turnover",
        metric="one_way_turnover",
        label_name=primary,
        limit=500,
    )
    assert turnover["total"] > 0
    assert all(float(item["value"]) >= 0 for item in turnover["items"])

    coverage = projection.query(
        feature_digest=first_factor,
        series_kind="coverage",
        metric="coverage",
        limit=500,
    )
    assert coverage["total"] > 0
    assert all(0.0 <= float(item["value"]) <= 1.0 for item in coverage["items"])

    with pytest.raises(ValueError, match="limit"):
        projection.query(limit=5001)
    with pytest.raises(ValueError, match="series_kind"):
        projection.query(series_kind="unknown")

    replay_manifest_path = root / "robust.factor-series-replay.json"
    replay_data_path = root / "robust.factor-series-replay.parquet"
    second = _run_v41(
        config=config,
        report=report,
        manifest=replay_manifest_path,
        data=replay_data_path,
    )
    assert second.returncode == 0, second.stderr + second.stdout
    replay = FactorSeriesManifest.read_json(replay_manifest_path)
    assert replay.series_id == manifest.series_id
    assert replay.rows_digest == manifest.rows_digest
    assert replay.quant_config_digest == manifest.quant_config_digest
    assert report.read_bytes() == report_before


def test_v41_projection_fails_closed_on_source_parquet_or_manifest_tamper(
    v41_evidence: dict[str, object],
    tmp_path: Path,
) -> None:
    report = Path(v41_evidence["report"])
    manifest = Path(v41_evidence["manifest"])
    data = Path(v41_evidence["data"])

    tamper_root = tmp_path / "tamper"
    tamper_root.mkdir()
    report_copy = tamper_root / report.name
    manifest_copy = tamper_root / manifest.name
    data_copy = tamper_root / data.name
    shutil.copy2(report, report_copy)
    shutil.copy2(manifest, manifest_copy)
    shutil.copy2(data, data_copy)

    report_copy.write_text(
        report_copy.read_text(encoding="utf-8") + " ",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="report SHA-256"):
        FactorSeriesProjection(manifest_copy)

    shutil.copy2(report, report_copy)
    with data_copy.open("ab") as handle:
        handle.write(b"tamper")
    with pytest.raises(ValueError, match="Parquet SHA-256"):
        FactorSeriesProjection(manifest_copy)

    shutil.copy2(data, data_copy)
    manifest_payload = json.loads(manifest_copy.read_text(encoding="utf-8"))
    manifest_payload["primary_label"] = "tampered_forward_label"
    manifest_copy.write_text(
        json.dumps(manifest_payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="manifest quant metadata drift: primary_label"):
        FactorSeriesProjection(manifest_copy)
