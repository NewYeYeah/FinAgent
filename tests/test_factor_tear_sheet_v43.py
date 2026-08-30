from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from finagent.research.factor_series import FactorSeriesManifest
from finagent.visualization.factor_tear_sheet import FactorTearSheetProjection
from finagent.visualization.workbench_api import create_workspace_app

pytest_plugins = ("tests.test_factor_series_v41",)


def test_v43a_projection_exposes_v41_rows_and_frozen_a2p6_summary(
    v41_evidence: dict[str, object],
) -> None:
    root = Path(v41_evidence["root"])
    manifest_path = Path(v41_evidence["manifest"])
    manifest = FactorSeriesManifest.read_json(manifest_path)
    projection = FactorTearSheetProjection((root,))

    status = projection.status()
    assert status["series_count"] == 1
    assert status["browser_recomputation"] is False
    assert status["period_evidence"] == "v4_1_persisted_authority"
    assert status["statistical_summary"] == "frozen_a2p6_authoritative"

    catalog = projection.catalog()
    assert catalog["warnings"] == []
    assert catalog["items"][0]["series_id"] == manifest.series_id
    assert catalog["items"][0]["program_id"] == manifest.program_id
    assert projection.by_program(manifest.program_id).series_id == manifest.series_id

    dimensions = projection.dimensions(manifest.series_id)
    assert {item["feature_digest"] for item in dimensions["factors"]} == set(
        manifest.candidate_feature_digests
    )
    assert dimensions["primary_label"] == manifest.primary_label
    assert dimensions["decay_labels"] == list(manifest.decay_labels)
    assert dimensions["quantiles"] == list(range(1, manifest.quantiles + 1))
    assert len(dimensions["folds"]) == manifest.fold_count
    assert "rank_ic" in dimensions["metric_authority"]["authoritative"]
    assert "rolling_rank_ic" in dimensions["metric_authority"]["derived"]
    assert "nav" in dimensions["metric_authority"]["derived"]

    first_factor = manifest.candidate_feature_digests[0]
    authoritative = projection.query(
        manifest.series_id,
        feature_digest=first_factor,
        series_kind="ic",
        metric="rank_ic",
        label_name=manifest.primary_label,
        limit=500,
    )
    assert authoritative["items"]
    assert all(item["authority"] == "authoritative" for item in authoritative["items"])

    rolling = projection.query(
        manifest.series_id,
        feature_digest=first_factor,
        series_kind="ic",
        metric="rolling_rank_ic",
        label_name=manifest.primary_label,
        limit=500,
    )
    assert rolling["items"]
    assert all(item["authority"] == "derived" for item in rolling["items"])
    assert all(
        int(item["window_count"]) == manifest.rolling_window
        for item in rolling["items"]
    )

    summary = projection.frozen_summary(manifest.series_id)
    assert summary["authority"] == "authoritative_frozen_a2p6_summary"
    assert summary["statistics_recomputed"] is False
    assert summary["statistics_projection"] == "source_structure_plus_direct_field_aliases"
    assert len(summary["items"]) == manifest.factor_count
    factor = next(
        item for item in summary["items"] if item["feature_digest"] == first_factor
    )
    statistics = factor["statistics"]
    assert statistics["hac_tstat"] == statistics["hac"]["tstat"]
    assert statistics["raw_hac_pvalue"] == statistics["hac"]["raw_pvalue"]
    assert (
        statistics["holm_adjusted_pvalue"]
        == statistics["hac"]["holm_adjusted_pvalue"]
    )
    assert statistics["bh_qvalue"] == statistics["hac"]["bh_qvalue"]
    assert (
        statistics["bootstrap_pvalue"]
        == statistics["block_bootstrap"]["pvalue"]
    )
    assert (
        statistics["bootstrap_ci_lower"]
        == statistics["block_bootstrap"]["ci_lower"]
    )
    assert (
        statistics["bootstrap_ci_upper"]
        == statistics["block_bootstrap"]["ci_upper"]
    )
    assert factor["folds"]
    assert factor["gate"] is not None


def test_v43a_factor_api_is_get_only_bounded_and_preserves_authority(
    v41_evidence: dict[str, object],
) -> None:
    root = Path(v41_evidence["root"])
    manifest = FactorSeriesManifest.read_json(Path(v41_evidence["manifest"]))
    app = create_workspace_app(
        report_paths=(root,),
        config_paths=(),
        frontend_dir=None,
    )
    client = TestClient(app)

    status = client.get("/api/v3/workbench/status")
    assert status.status_code == 200
    factor_status = status.json()["factor_tear_sheet"]
    assert factor_status["series_count"] == 1
    assert factor_status["browser_recomputation"] is False

    catalog = client.get("/api/v4/factor-series")
    assert catalog.status_code == 200
    assert catalog.json()["items"][0]["series_id"] == manifest.series_id

    by_program = client.get(
        f"/api/v4/factor-series/by-program/{manifest.program_id}"
    )
    assert by_program.status_code == 200
    assert by_program.json()["series_id"] == manifest.series_id

    detail = client.get(f"/api/v4/factor-series/{manifest.series_id}")
    assert detail.status_code == 200
    presentation = detail.json()["presentation"]
    assert presentation["browser_recomputation"] is False
    assert "rolling_rank_ic" in presentation["derived_metrics"]
    assert "nav" in presentation["derived_metrics"]

    dimensions = client.get(
        f"/api/v4/factor-series/{manifest.series_id}/dimensions"
    )
    assert dimensions.status_code == 200
    assert dimensions.json()["program_id"] == manifest.program_id

    summary = client.get(f"/api/v4/factor-series/{manifest.series_id}/summary")
    assert summary.status_code == 200
    assert summary.json()["statistics_recomputed"] is False
    assert (
        summary.json()["statistics_projection"]
        == "source_structure_plus_direct_field_aliases"
    )

    first_factor = manifest.candidate_feature_digests[0]
    rows = client.get(
        f"/api/v4/factor-series/{manifest.series_id}/rows",
        params={
            "feature_digest": first_factor,
            "series_kind": "ic",
            "metric": "rank_ic",
            "label_name": manifest.primary_label,
            "limit": 500,
        },
    )
    assert rows.status_code == 200
    assert rows.json()["items"]
    assert all(
        item["authority"] == "authoritative" for item in rows.json()["items"]
    )

    rolling = client.get(
        f"/api/v4/factor-series/{manifest.series_id}/rows",
        params={
            "feature_digest": first_factor,
            "series_kind": "ic",
            "metric": "rolling_rank_ic",
            "label_name": manifest.primary_label,
            "limit": 500,
        },
    )
    assert rolling.status_code == 200
    assert rolling.json()["items"]
    assert all(item["authority"] == "derived" for item in rolling.json()["items"])

    invalid = client.get(
        f"/api/v4/factor-series/{manifest.series_id}/rows",
        params={"limit": 5001},
    )
    assert invalid.status_code == 422

    for path in (
        "/api/v4/factor-series",
        f"/api/v4/factor-series/{manifest.series_id}",
        f"/api/v4/factor-series/{manifest.series_id}/dimensions",
        f"/api/v4/factor-series/{manifest.series_id}/summary",
        f"/api/v4/factor-series/{manifest.series_id}/rows",
    ):
        response = client.post(path)
        assert response.status_code == 405
