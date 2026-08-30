from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from finagent.visualization.factor_tearsheet import FactorTearSheetProjection
from finagent.visualization.workbench_api import create_workspace_app
from tests.test_factor_series_v41 import v41_evidence  # noqa: F401


def test_v43_projects_verified_factor_series_and_frozen_statistics(
    v41_evidence: dict[str, object],
) -> None:
    root = Path(v41_evidence["root"])
    projection = FactorTearSheetProjection((root,))
    catalog = projection.catalog()
    assert catalog["read_only"] is True
    assert catalog["warnings"] == []
    assert len(catalog["items"]) == 1
    item = catalog["items"][0]
    series_id = str(item["series_id"])
    program_id = str(item["program_id"])
    assert item["factor_count"] == 3
    assert projection.by_program(program_id).series_id == series_id

    dimensions = projection.dimensions(series_id)
    assert dimensions["authority"] == "authoritative_identity_dimensions"
    assert len(dimensions["factors"]) == 3
    assert len(dimensions["folds"]) == 2
    assert dimensions["primary_label"]
    assert dimensions["quantiles"] == [1, 2, 3]
    assert dimensions["rolling_window"] == 20

    first_factor = str(dimensions["factors"][0]["feature_digest"])
    summary = projection.summary(series_id, feature_digest=first_factor)
    assert summary["authority"] == "authoritative_frozen_a2p6_summary"
    assert len(summary["items"]) == 1
    candidate = summary["items"][0]
    assert candidate["feature_digest"] == first_factor
    assert "pooled_rank_icir" in candidate["metrics"]
    assert "holm_adjusted_pvalue" in candidate["hac"]
    assert "ci_lower" in candidate["block_bootstrap"]
    assert candidate["folds"]

    heatmap = projection.heatmap(series_id, feature_digest=first_factor)
    assert heatmap["authority"] == "derived_presentation"
    assert heatmap["source_authority"] == "authoritative_v4_1_period_rows"
    assert heatmap["metric"] == "rank_ic"
    assert heatmap["cells"]

    correlations = projection.correlations(series_id)
    assert correlations["correlation_authority"] == "authoritative_frozen_a2p6_summary"
    assert correlations["cluster_authority"] == "derived_presentation"
    assert len(correlations["factors"]) == 3
    assert len(correlations["cells"]) == 9
    assert set(correlations["cluster_order"]) == set(correlations["factors"])

    provenance = projection.provenance(series_id)
    assert provenance["agent_chronology_available"] is False
    assert provenance["ordering_semantics"] == "frozen_candidate_denominator_order_only"
    assert len(provenance["items"]) == 3
    assert all("generator_id" in row for row in provenance["items"])

    rows = projection.query(
        series_id,
        feature_digest=first_factor,
        series_kind="ic",
        metric="rolling_rank_ic",
        label_name=str(dimensions["primary_label"]),
        limit=5000,
    )
    assert rows["items"]
    assert all(row["authority"] == "derived" for row in rows["items"])


def test_v43_api_is_get_only_bounded_and_context_ready(
    v41_evidence: dict[str, object],
) -> None:
    root = Path(v41_evidence["root"])
    app = create_workspace_app(
        report_paths=(root,),
        config_paths=(),
        frontend_dir=None,
    )
    client = TestClient(app)

    status = client.get("/api/v3/workbench/status")
    assert status.status_code == 200
    assert status.json()["version"] == "finagent-workbench-api-v4.3"
    assert status.json()["factor_tearsheet"]["series_count"] == 1
    assert status.json()["factor_tearsheet"]["browser_recomputation"] is False

    catalog = client.get("/api/v4/factor-series")
    assert catalog.status_code == 200
    item = catalog.json()["items"][0]
    series_id = item["series_id"]
    program_id = item["program_id"]
    first_factor = item["candidate_feature_digests"][0]

    by_program = client.get(f"/api/v4/factor-series/by-program/{program_id}")
    assert by_program.status_code == 200
    assert by_program.json()["series_id"] == series_id

    detail = client.get(f"/api/v4/factor-series/{series_id}")
    assert detail.status_code == 200
    assert detail.json()["presentation"]["browser_recomputation"] is False
    assert detail.json()["presentation"]["agent_chronology_available"] is False

    for suffix in ("dimensions", "summary", "correlations", "provenance"):
        response = client.get(f"/api/v4/factor-series/{series_id}/{suffix}")
        assert response.status_code == 200

    heatmap = client.get(
        f"/api/v4/factor-series/{series_id}/heatmap",
        params={"feature_digest": first_factor, "metric": "rank_ic"},
    )
    assert heatmap.status_code == 200
    assert heatmap.json()["authority"] == "derived_presentation"

    rows = client.get(
        f"/api/v4/factor-series/{series_id}/rows",
        params={
            "feature_digest": first_factor,
            "series_kind": "ic",
            "metric": "rank_ic",
            "limit": 5000,
        },
    )
    assert rows.status_code == 200
    assert rows.json()["total"] > 0

    too_large = client.get(
        f"/api/v4/factor-series/{series_id}/rows",
        params={"limit": 5001},
    )
    assert too_large.status_code == 422

    for path in (
        "/api/v4/factor-series",
        f"/api/v4/factor-series/{series_id}",
        f"/api/v4/factor-series/{series_id}/dimensions",
        f"/api/v4/factor-series/{series_id}/summary",
        f"/api/v4/factor-series/{series_id}/correlations",
        f"/api/v4/factor-series/{series_id}/heatmap",
        f"/api/v4/factor-series/{series_id}/provenance",
        f"/api/v4/factor-series/{series_id}/rows",
    ):
        assert client.post(path).status_code == 405
