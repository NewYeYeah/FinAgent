from __future__ import annotations

import builtins
import json
from pathlib import Path

from finagent.visualization.strategy_explorer import StrategyDecisionExplorerProjection


def test_v42_missing_duckdb_degrades_to_warning_not_workspace_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    manifest = tmp_path / "decision-series.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "finagent.strategy-decision-series.manifest.v1",
                "authority": "authoritative",
                "series_id": "strategy-decision-series-missing-duckdb",
                "portfolio_validation_id": "a4-missing-duckdb",
                "a4_spec_id": "a4-spec-missing-duckdb",
                "source_program_result_id": "program-result-missing-duckdb",
                "source_program_spec_id": "program-spec-missing-duckdb",
                "source_program_report_digest": "a" * 64,
                "source_selection_id": "selection-missing-duckdb",
                "data_version": "data-missing-duckdb",
                "execution_ledger_digest": "ledger-missing-duckdb",
                "selected_feature_digests": ["factor-missing-duckdb"],
                "alpha_model_ids": ["alpha-model-missing-duckdb"],
                "rows_digest": "rows-missing-duckdb",
                "source_report_file": "a4.json",
                "source_report_sha256": "b" * 64,
                "source_ledger_file": "a4.jsonl",
                "source_ledger_sha256": "c" * 64,
                "data_file": "a4.parquet",
                "data_sha256": "d" * 64,
                "row_count": 1,
                "source_session_count": 1,
                "row_session_count": 1,
                "asset_count": 1,
                "start_date": "2024-01-02",
                "end_date": "2024-01-02",
                "columns": [],
                "nullable_columns": [],
            }
        ),
        encoding="utf-8",
    )

    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "duckdb":
            raise ImportError("duckdb intentionally unavailable")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    projection = StrategyDecisionExplorerProjection((tmp_path,))
    assert projection.catalog()["items"] == []
    assert projection.status()["series_count"] == 0
    assert projection.status()["warning_count"] == 1
    assert "local-parquet" in projection.warnings[0]
