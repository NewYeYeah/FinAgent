from __future__ import annotations

import copy
from pathlib import Path

import pytest

from finagent.visualization.factor_tearsheet import FactorTearSheetProjection

pytest_plugins = ("tests.test_factor_series_v41",)


def _projection(v41_evidence: dict[str, object]) -> tuple[FactorTearSheetProjection, str]:
    projection = FactorTearSheetProjection((Path(v41_evidence["root"]),))
    catalog = projection.catalog()
    assert len(catalog["items"]) == 1
    return projection, str(catalog["items"][0]["series_id"])


def _mutable_report(
    projection: FactorTearSheetProjection,
    series_id: str,
) -> dict[str, object]:
    return copy.deepcopy(dict(projection.report(series_id)))


def test_v43_dimensions_copy_v41_metric_authority(
    v41_evidence: dict[str, object],
) -> None:
    projection, series_id = _projection(v41_evidence)
    manifest = projection.projection(series_id).manifest

    dimensions = projection.dimensions(series_id)

    assert dimensions["metric_authority"] == manifest.to_dict()["metric_authority"]


def test_v43_summary_fails_closed_when_frozen_hac_statistic_is_missing(
    v41_evidence: dict[str, object],
) -> None:
    projection, series_id = _projection(v41_evidence)
    report = _mutable_report(projection, series_id)
    walk = report["walk_forward_report"]
    assert isinstance(walk, dict)
    candidates = walk["candidates"]
    assert isinstance(candidates, list) and candidates
    candidate = candidates[0]
    assert isinstance(candidate, dict)
    hac = candidate["hac"]
    assert isinstance(hac, dict)
    hac.pop("tstat")
    projection._reports[series_id] = report

    with pytest.raises(ValueError, match="hac.tstat"):
        projection.summary(series_id)


def test_v43_summary_fails_closed_when_selection_denominator_drifts(
    v41_evidence: dict[str, object],
) -> None:
    projection, series_id = _projection(v41_evidence)
    report = _mutable_report(projection, series_id)
    selection = report["frozen_selection"]
    assert isinstance(selection, dict)
    components = selection["components"]
    assert isinstance(components, list) and components
    components.pop()
    projection._reports[series_id] = report

    with pytest.raises(ValueError, match="selection components differ"):
        projection.summary(series_id)


def test_v43_correlations_require_every_frozen_pair_and_label_diagonal_derivation(
    v41_evidence: dict[str, object],
) -> None:
    projection, series_id = _projection(v41_evidence)
    correlations = projection.correlations(series_id)
    cells = correlations["cells"]
    assert isinstance(cells, list)
    assert any(
        cell["left"] == cell["right"]
        and cell["authority"] == "derived_presentation_identity"
        for cell in cells
    )
    assert any(
        cell["left"] != cell["right"]
        and cell["authority"] == "authoritative_frozen_a2p6_summary"
        for cell in cells
    )
    assert correlations["diagonal_authority"] == "derived_presentation_identity"
    assert correlations["cluster_authority"] == "derived_presentation"

    report = _mutable_report(projection, series_id)
    walk = report["walk_forward_report"]
    assert isinstance(walk, dict)
    frozen = walk["factor_value_correlations"]
    assert isinstance(frozen, dict) and frozen
    frozen.pop(next(iter(frozen)))
    projection._reports[series_id] = report

    with pytest.raises(ValueError, match="factor correlations do not match"):
        projection.correlations(series_id)
