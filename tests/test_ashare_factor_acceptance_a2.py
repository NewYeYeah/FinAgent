from __future__ import annotations

import csv
import json
import subprocess
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import duckdb
import numpy as np

from finagent.agents.generated_features import (
    FeatureCodeValidator,
    FeatureSpec,
    GeneratedFeatureArtifact,
)
from finagent.data import (
    AshareBarFrequency,
    LocalAshareDatasetLayout,
    LocalAshareParquetDataAdapter,
    LocalAshareSecurityMaster,
    create_local_ashare_frozen_manifest,
)
from finagent.domain.research import DatasetRequest, TimeRange
from finagent.research.ashare_universe import (
    AshareCandidateUniverseConfig,
    AshareCandidateUniverseSelector,
    AshareResearchUniversePolicy,
    AshareResearchUniversePolicyConfig,
)
from finagent.research.factor_quant import FactorQuantAnalyzer, FactorQuantConfig
from finagent.research.panel_feature_materializer import PanelGeneratedFeatureMaterializer

ROOT = Path(__file__).resolve().parents[1]


def _write_parquet(csv_path: Path, parquet_path: Path) -> None:
    source = csv_path.resolve().as_posix().replace("'", "''")
    target = parquet_path.resolve().as_posix().replace("'", "''")
    duckdb.connect().execute(
        f"COPY (SELECT * FROM read_csv_auto('{source}', header=true)) "
        f"TO '{target}' (FORMAT PARQUET)"
    )


def _vendor(root: Path, *, assets: int = 10, days: int = 180) -> tuple[str, ...]:
    root.mkdir(parents=True, exist_ok=True)
    codes = tuple(f"000{index + 1:03d}.SZ" for index in range(assets))
    basic = root / "basic.csv"
    with basic.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["ts_code", "name", "market", "list_date", "delist_date", "list_status"])
        for index, code in enumerate(codes):
            writer.writerow([code, f"A2-{index}", "主板", "2018-01-01", "", ""])
    _write_parquet(basic, root / "stock_basic_data.parquet")

    trading_days: list[date] = []
    cursor = date(2020, 1, 2)
    while len(trading_days) < days:
        if cursor.weekday() < 5:
            trading_days.append(cursor)
        cursor += timedelta(days=1)
    daily = root / "daily.csv"
    fields = [
        "ts_code",
        "trade_date",
        "open",
        "high",
        "low",
        "close",
        "pre_close",
        "vol",
        "amount",
        "adj_factor",
        "turnover_rate",
        "circ_mv",
        "listed_days",
        "is_st",
    ]
    with daily.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for asset_index, code in enumerate(codes):
            previous = 8.0 + asset_index
            for row_index, day in enumerate(trading_days):
                signal = 0.0015 * np.sin(row_index / 7.0 + asset_index * 0.55)
                cross = 0.00035 * (asset_index - assets / 2)
                close = previous * (1.0 + signal + cross)
                open_ = previous * (1.0 + 0.0002 * ((row_index + asset_index) % 3 - 1))
                writer.writerow(
                    {
                        "ts_code": code,
                        "trade_date": day.isoformat(),
                        "open": f"{open_:.8f}",
                        "high": f"{max(open_, close) * 1.01:.8f}",
                        "low": f"{min(open_, close) * 0.99:.8f}",
                        "close": f"{close:.8f}",
                        "pre_close": f"{previous:.8f}",
                        "vol": 2000 + 25 * row_index + 100 * asset_index,
                        "amount": 25_000 + 100 * row_index + 1500 * asset_index,
                        "adj_factor": 1.0,
                        "turnover_rate": 1.0 + asset_index * 0.08,
                        "circ_mv": 100_000 + 25_000 * asset_index,
                        "listed_days": 500 + row_index,
                        "is_st": 1 if asset_index == assets - 1 and 70 <= row_index < 80 else 0,
                    }
                )
                previous = close
    _write_parquet(daily, root / "stock_daily.parquet")
    return codes


def _reference(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "sources.toml").write_text(
        """
[dataset]
coverage = "partial"
notes = "A2 test"

[sources.test]
name = "Test"
authority = "TEST"
url = "https://example.test"
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (root / "delistings.csv").write_text(
        "ts_code,effective_date,decision_date,source_id,source_url,observed_at,notes\n",
        encoding="utf-8",
    )
    (root / "st_periods.csv").write_text(
        "ts_code,start_date,end_date,status,source_id,source_url,observed_at,notes\n",
        encoding="utf-8",
    )
    (root / "suspensions.csv").write_text(
        "ts_code,start_time,end_time,reason,source_id,source_url,observed_at,notes\n",
        encoding="utf-8",
    )


def _artifact() -> GeneratedFeatureArtifact:
    source = 'def compute_feature(inputs):\n    return inputs["simple_return_5"]\n'
    validator = FeatureCodeValidator()
    return GeneratedFeatureArtifact(
        spec=FeatureSpec(
            feature_id="a2-panel-test",
            name="A2 panel test",
            description="panel-native test",
            hypothesis="five-session continuation",
            input_fields=("simple_return_5",),
            lookback=1,
        ),
        source=source,
        validation=validator.validate(source),
        generated_at=datetime(2026, 8, 27, tzinfo=UTC),
        generator_id="test",
        smoke_output_digest="test-smoke",
    )


def test_panel_materializer_and_universe_policy_use_batched_local_panel(tmp_path) -> None:
    vendor = tmp_path / "vendor"
    _vendor(vendor, assets=8, days=90)
    layout = LocalAshareDatasetLayout(vendor)
    master = LocalAshareSecurityMaster.from_parquet(layout.basic_path)
    adapter = LocalAshareParquetDataAdapter(
        layout,
        frequency=AshareBarFrequency.DAILY,
        security_master=master,
        data_version="a2-panel-data",
    )
    selection = AshareCandidateUniverseSelector(
        layout,
        master,
        data_version=adapter.data_version,
    ).select(
        AshareCandidateUniverseConfig(
            selection_date=date(2020, 2, 28),
            top_n=7,
            min_universe_size=6,
            min_listed_days=100,
            min_amount_cny=1_000_000,
        )
    )
    start = datetime(2020, 3, 2, tzinfo=UTC)
    end = datetime(2020, 5, 15, tzinfo=UTC)
    request = DatasetRequest(
        universe=selection.assets,
        features=("simple_return_5",),
        labels=("forward_simple_return_1",),
        splits={"development": TimeRange(start, end)},
        dataset_id="a2-panel-request",
    )
    provider, report = AshareResearchUniversePolicy(
        AshareResearchUniversePolicyConfig(
            min_listed_days=100,
            min_close=1.0,
            min_median_amount_cny=1_000_000,
            liquidity_lookback=5,
            min_liquidity_observations=3,
        )
    ).build(adapter, request, candidate_selection_id=selection.selection_id)
    materializer = PanelGeneratedFeatureMaterializer(
        adapter,
        universe_provider=provider,
        batch_size=64,
    )
    analyzer = FactorQuantAnalyzer(
        adapter,
        config=FactorQuantConfig(
            split_name="development",
            primary_label="forward_simple_return_1",
            quantiles=3,
            min_cross_section=5,
            min_periods=10,
        ),
        materializer=materializer,
    )
    result = analyzer.analyze((_artifact(),), request=request)
    assert result.candidates[0].primary.periods >= 10
    assert report.splits["development"].average_eligible_assets >= 5


def test_a2_cli_runs_deterministic_factor_acceptance_and_exact_replay(tmp_path) -> None:
    vendor = tmp_path / "vendor"
    _vendor(vendor, assets=10, days=180)
    reference = tmp_path / "reference"
    _reference(reference)
    layout = LocalAshareDatasetLayout(vendor)
    manifest = create_local_ashare_frozen_manifest(
        layout,
        frequencies=(AshareBarFrequency.DAILY,),
        content_hash=False,
        created_at=datetime(2026, 8, 27, tzinfo=UTC),
    )
    manifest_path = tmp_path / "manifest.json"
    manifest.write_json(manifest_path)
    state = tmp_path / "state"
    report = tmp_path / "report.json"
    replay = tmp_path / "replay.json"
    config = tmp_path / "a2.toml"
    config.write_text(
        f'''
[local_ashare_factor_research]
mode = "deterministic"
root = "{vendor.as_posix()}"
frozen_manifest = "{manifest_path.as_posix()}"
supplement_root = "{reference.as_posix()}"
state_dir = "{state.as_posix()}"
report_path = "{report.as_posix()}"
universe_selection_date = 2020-02-28
universe_top_n = 8
min_universe_size = 6
include_bse = false
selection_min_listed_days = 100
selection_min_close = 1.0
selection_min_amount_cny = 1000000.0
selection_exclude_st = true
development_start = 2020-03-02
development_end_exclusive = 2020-06-01
validation_start = 2020-06-01
validation_end_exclusive = 2020-08-31
reserve_start = 2020-08-31
reserve_end_exclusive = 2020-10-01
approved_input_fields = ["simple_return_1", "simple_return_5", "simple_return_20", "log_volume_change_5", "squared_log_return_1", "circ_mv"]
primary_label = "forward_simple_return_1"
decay_labels = ["forward_simple_return_5"]
policy_min_listed_days = 100
policy_exclude_st = true
policy_min_close = 1.0
policy_min_median_amount_cny = 1000000.0
policy_liquidity_lookback = 5
policy_min_liquidity_observations = 3
quantiles = 3
min_cross_section = 5
min_periods = 15
ensemble_max_factors = 2
ensemble_max_abs_factor_correlation = 0.99
ensemble_quality_metric = "rank_icir"
sandbox_batch_size = 64
smoke_lookback = 30

[[local_ashare_factor_research.baseline_factors]]
feature_id = "a2-test-momentum"
description = "momentum"
hypothesis = "continuation"
input_fields = ["simple_return_20"]
lookback = 1
source = """
def compute_feature(inputs):
    return inputs["simple_return_20"]
"""

[[local_ashare_factor_research.baseline_factors]]
feature_id = "a2-test-reversal"
description = "reversal"
hypothesis = "reversal"
input_fields = ["simple_return_5"]
lookback = 1
source = """
def compute_feature(inputs):
    return [None if value is None else -value for value in inputs["simple_return_5"]]
"""

[[local_ashare_factor_research.baseline_factors]]
feature_id = "a2-test-size"
description = "size"
hypothesis = "size premium"
input_fields = ["circ_mv"]
lookback = 1
source = """
def compute_feature(inputs):
    return [None if value is None else -math.log(value) for value in inputs["circ_mv"]]
"""
'''.strip()
        + "\n",
        encoding="utf-8",
    )
    command = [
        sys.executable,
        str(ROOT / "scripts" / "run_local_ashare_factor_research.py"),
        str(config),
    ]
    first = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    assert first.returncode == 0, first.stderr + first.stdout
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["passed"] is True
    assert payload["mode"] == "deterministic"
    assert payload["reserve"]["status"] == "untouched"
    assert len(payload["candidate_denominator"]) == 3
    assert payload["candidate_universe"]["size"] >= 6
    assert payload["validation_ensemble"]["primary_label"] == "forward_simple_return_1"
    assert "transaction_cost" not in payload["validation_comparison"]

    second = subprocess.run(
        [
            *command,
            "--frozen-report",
            str(report),
            "--assert-replay",
            "--report",
            str(replay),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert second.returncode == 0, second.stderr + second.stdout
    replay_payload = json.loads(replay.read_text(encoding="utf-8"))
    assert replay_payload["mode"] == "replay"
    assert replay_payload["acceptance_id"] == payload["acceptance_id"]
    assert replay_payload["development_report"]["report_id"] == payload["development_report"]["report_id"]
    assert replay_payload["validation_report"]["report_id"] == payload["validation_report"]["report_id"]
