from __future__ import annotations

import builtins
from pathlib import Path

from finagent.visualization.strategy_explorer import StrategyDecisionExplorerProjection
from tests.test_strategy_explorer_v42 import _write_v40


def test_v42_missing_duckdb_degrades_to_warning_not_workspace_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _write_v40(tmp_path)
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
