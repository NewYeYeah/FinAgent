from __future__ import annotations

import json
import shutil
from pathlib import Path

from fastapi.testclient import TestClient

from finagent.backtest import (
    canonical_execution_ledger_digest,
    materialize_strategy_decision_rows,
    write_strategy_decision_series,
)
from finagent.visualization.strategy_explorer import StrategyDecisionExplorerProjection
from finagent.visualization.workbench_api import create_workspace_app
from tests.test_strategy_decision_series_v40 import (
    ASSET,
    _alpha,
    _synthetic_ledger,
    _write_jsonl,
)


def _write_v40(tmp_path: Path) -> tuple[Path, str, str]:
    ledger = _synthetic_ledger()
    ledger_digest = canonical_execution_ledger_digest(ledger)
    report = {
        "schema_version": "finagent.ashare-portfolio-validation.v1",
        "portfolio_validation_id": "a4-validation-v42",
        "ledger_digest": ledger_digest,
        "validation_spec": {
            "spec_id": "a4-spec-v42",
            "source_program_result_id": "program-result-v42",
            "source_program_spec_id": "program-spec-v42",
            "source_selection_id": "selection-v42",
            "source_report_digest": "f" * 64,
            "data_version": "data-v42",
            "selected_feature_digests": ["factor-v42"],
            "selected_weights": [1.0],
            "selected_directions": [1],
            "validation_config": {"initial_cash": 1000.0},
        },
    }
    report_path = tmp_path / "a4.json"
    ledger_path = tmp_path / "a4.jsonl"
    manifest_path = tmp_path / "a4.strategy-decisions.json"
    data_path = tmp_path / "a4.strategy-decisions.parquet"
    report_path.write_text(json.dumps(report, sort_keys=True), encoding="utf-8")
    _write_jsonl(ledger_path, ledger)
    rows = materialize_strategy_decision_rows(
        ledger_rows=ledger,
        expected_ledger_digest=ledger_digest,
        initial_cash=1000.0,
        alpha_provider=_alpha,
    )
    manifest = write_strategy_decision_series(
        a4_report=report,
        rows=rows,
        source_report_path=report_path,
        source_ledger_path=ledger_path,
        manifest_path=manifest_path,
        data_path=data_path,
    )
    return manifest_path, manifest.series_id, manifest.portfolio_validation_id


def test_v42_projection_discovers_verified_series_and_dimensions(tmp_path: Path) -> None:
    _, series_id, validation_id = _write_v40(tmp_path)
    projection = StrategyDecisionExplorerProjection((tmp_path,))
    catalog = projection.catalog()
    assert catalog["read_only"] is True
    assert catalog["warnings"] == []
    assert len(catalog["items"]) == 1
    item = catalog["items"][0]
    assert item["series_id"] == series_id
    assert item["portfolio_validation_id"] == validation_id
    assert item["authority"] == "authoritative"

    dimensions = projection.dimensions(series_id)
    assert dimensions["assets"] == [ASSET]
    assert dimensions["folds"] == ["wf-1"]
    assert dimensions["session_count"] == 2
    assert dimensions["start_date"] == "2024-01-02"
    assert dimensions["end_date"] == "2024-01-03"
    assert dimensions["ohlc_available"] is False

    selected = projection.query(series_id, asset=ASSET, limit=10)
    assert selected["total"] == 2
    assert selected["items"][0]["close_price"] == 11.0
    assert selected["items"][0]["fill_price"] == 10.1
    assert selected["items"][0]["alpha_score"] == 1.25
    assert projection.by_portfolio(validation_id).series_id == series_id


def test_v42_equivalent_rematerialization_is_deduplicated(tmp_path: Path) -> None:
    manifest_path, series_id, _ = _write_v40(tmp_path)
    original = json.loads(manifest_path.read_text(encoding="utf-8"))
    original_data = tmp_path / str(original["data_file"])
    replay_data = tmp_path / "a4.strategy-decisions-replay.parquet"
    replay_manifest = tmp_path / "a4.strategy-decisions-replay.json"
    shutil.copy2(original_data, replay_data)
    replay = dict(original)
    replay["data_file"] = replay_data.name
    replay_manifest.write_text(
        json.dumps(replay, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    projection = StrategyDecisionExplorerProjection((tmp_path,))
    catalog = projection.catalog()
    assert len(catalog["items"]) == 1
    assert catalog["items"][0]["series_id"] == series_id
    assert catalog["warnings"] == []
    assert any("equivalent StrategyDecisionSeries" in notice for notice in catalog["notices"])


def test_v42_evidence_api_is_get_only_and_bounded(tmp_path: Path) -> None:
    _, series_id, validation_id = _write_v40(tmp_path)
    app = create_workspace_app(
        report_paths=(tmp_path,),
        config_paths=(),
        frontend_dir=None,
    )
    client = TestClient(app)

    status = client.get("/api/v3/workbench/status")
    assert status.status_code == 200
    strategy_status = status.json()["strategy_explorer"]
    assert strategy_status["series_count"] == 1
    assert strategy_status["ohlc_available"] is False
    assert strategy_status["browser_recomputation"] is False

    catalog = client.get("/api/v4/strategy-series")
    assert catalog.status_code == 200
    assert catalog.json()["items"][0]["series_id"] == series_id

    by_portfolio = client.get(
        f"/api/v4/strategy-series/by-portfolio/{validation_id}"
    )
    assert by_portfolio.status_code == 200
    assert by_portfolio.json()["series_id"] == series_id

    detail = client.get(f"/api/v4/strategy-series/{series_id}")
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["read_only"] is True
    assert payload["presentation"]["price_semantics"] == "authoritative_close_only"
    assert payload["presentation"]["ohlc_available"] is False
    assert payload["presentation"]["browser_recomputation"] is False

    dimensions = client.get(f"/api/v4/strategy-series/{series_id}/dimensions")
    assert dimensions.status_code == 200
    assert dimensions.json()["assets"] == [ASSET]

    decisions = client.get(
        f"/api/v4/strategy-series/{series_id}/decisions",
        params={"asset": ASSET, "start": "2024-01-02", "end": "2024-01-03"},
    )
    assert decisions.status_code == 200
    assert decisions.json()["total"] == 2
    assert decisions.json()["authority"] == "authoritative"

    invalid = client.get(
        f"/api/v4/strategy-series/{series_id}/decisions",
        params={"limit": 5001},
    )
    assert invalid.status_code == 422

    for path in (
        "/api/v4/strategy-series",
        f"/api/v4/strategy-series/{series_id}",
        f"/api/v4/strategy-series/{series_id}/dimensions",
        f"/api/v4/strategy-series/{series_id}/decisions",
    ):
        response = client.post(path)
        assert response.status_code == 405
