from pathlib import Path


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one target, found {count}: {old[:100]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


core = Path("src/finagent/research/replay_experiment_campaign.py")
replace_once(
    core,
    "_CAMPAIGN_SLICES = (\n    (BarInterval.MINUTE_5, 60),\n    (BarInterval.MINUTE_15, 30),\n    (BarInterval.MINUTE_15, 60),\n    (BarInterval.MINUTE_15, 120),\n    (BarInterval.MINUTE_30, 60),\n)\n\n\n",
    "_CAMPAIGN_SLICES = (\n    (BarInterval.MINUTE_5, 60),\n    (BarInterval.MINUTE_15, 30),\n    (BarInterval.MINUTE_15, 60),\n    (BarInterval.MINUTE_15, 120),\n    (BarInterval.MINUTE_30, 60),\n)\n_CAMPAIGN_SURFACES = frozenset(\n    {\n        \"rows:5m:60m\",\n        \"rows:15m:30m\",\n        \"rows:15m:60m\",\n        \"rows:15m:120m\",\n        \"rows:30m:60m\",\n        \"b0:observations\",\n        \"b0:materialization-diagnostics\",\n        \"b0:evaluation\",\n        \"a0:observations\",\n        \"a0:materialization-diagnostics\",\n        \"r1:TRAIN:15m:60m\",\n        \"r1:EVALUATION:5m:60m\",\n        \"r1:EVALUATION:15m:30m\",\n        \"r1:EVALUATION:15m:60m\",\n        \"r1:EVALUATION:15m:120m\",\n        \"r1:EVALUATION:30m:60m\",\n    }\n)\n\n\n",
)
replace_once(
    core,
    "    schema_version: str = \"finagent.replay-experiment-campaign-report.v1\"\n\n    @property\n    def blockers(self) -> tuple[str, ...]:\n",
    "    schema_version: str = \"finagent.replay-experiment-campaign-report.v1\"\n\n    def __post_init__(self) -> None:\n        for field_name in (\n            \"source_manifest_id\",\n            \"source_run_report_id\",\n            \"streaming_bundle_id\",\n            \"b0_run_spec_id\",\n            \"b0_denominator_id\",\n            \"a0_denominator_id\",\n            \"r1_denominator_id\",\n        ):\n            object.__setattr__(self, field_name, _text(getattr(self, field_name), field_name))\n        if self.b0_denominator_id != canonical_us_baseline_denominator().denominator_id:\n            raise ValueError(\"campaign report must bind the canonical B0 denominator\")\n        slice_keys = tuple(\n            (item.signal_interval, item.label_horizon_trading_minutes)\n            for item in self.batch_slices\n        )\n        if len(slice_keys) != len(_CAMPAIGN_SLICES) or set(slice_keys) != set(_CAMPAIGN_SLICES):\n            raise ValueError(\"campaign report requires the frozen five unique batch slices\")\n        surfaces = tuple(item.surface for item in self.parity_checks)\n        if len(surfaces) != len(_CAMPAIGN_SURFACES) or set(surfaces) != _CAMPAIGN_SURFACES:\n            raise ValueError(\"campaign report requires the frozen sixteen unique parity surfaces\")\n\n    @property\n    def blockers(self) -> tuple[str, ...]:\n",
)
replace_once(
    core,
    '            "engineering_only": True,\n            "certification_authority": False,\n',
    '            "engineering_only": True,\n            "formal_us_b0_operator_invoked": False,\n            "us_d3_certification_consumed": False,\n            "certification_authority": False,\n',
)

tests = Path("tests/test_replay_experiment_campaign_v1.py")
replace_once(
    tests,
    '    assert document["engineering_only"] is True\n    assert document["certification_authority"] is False\n',
    '    assert document["engineering_only"] is True\n    assert document["formal_us_b0_operator_invoked"] is False\n    assert document["us_d3_certification_consumed"] is False\n    assert document["certification_authority"] is False\n',
)

workflow = Path(".github/workflows/replay-experiment-campaign-v1.yml")
replace_once(
    workflow,
    '          operator = Path("scripts/materialize_us_b0_baselines.py").read_text(encoding="utf-8")\n          if "_require_us_b0_stage_authority" not in operator:\n              raise SystemExit("formal US-B0 operator lost its stage-authority guard")\n          PY\n      - name: Strict static checks\n',
    '          operator = Path("scripts/materialize_us_b0_baselines.py").read_text(encoding="utf-8")\n          if "_require_us_b0_stage_authority" not in operator:\n              raise SystemExit("formal US-B0 operator lost its stage-authority guard")\n          local_operator = Path("scripts/run_replay_experiment_campaign.py").read_text(encoding="utf-8")\n          if "materialize_us_b0_baselines" in local_operator:\n              raise SystemExit("engineering campaign operator must not call/import formal US-B0 operator")\n          PY\n      - name: Local bounded operator import/help smoke\n        run: uv run --frozen python scripts/run_replay_experiment_campaign.py --help\n      - name: Strict static checks\n',
)
replace_once(
    workflow,
    '          uv run --frozen ruff check \\\n            src/finagent/research/replay_experiment_campaign.py \\\n            src/finagent/research/streaming_experiment_bridge.py \\\n            tests/test_replay_experiment_campaign_v1.py\n          uv run --frozen mypy --strict \\\n            src/finagent/research/replay_experiment_campaign.py \\\n            src/finagent/research/streaming_experiment_bridge.py\n          uv run --frozen python -m py_compile \\\n            src/finagent/research/replay_experiment_campaign.py \\\n            src/finagent/research/streaming_experiment_bridge.py\n',
    '          uv run --frozen ruff check \\\n            src/finagent/research/replay_experiment_campaign.py \\\n            src/finagent/research/streaming_experiment_bridge.py \\\n            scripts/smoke_replay_experiment_campaign.py \\\n            scripts/run_replay_experiment_campaign.py \\\n            tests/test_replay_experiment_campaign_v1.py\n          uv run --frozen mypy --strict \\\n            src/finagent/research/replay_experiment_campaign.py \\\n            src/finagent/research/streaming_experiment_bridge.py \\\n            scripts/smoke_replay_experiment_campaign.py\n          uv run --frozen python -m py_compile \\\n            src/finagent/research/replay_experiment_campaign.py \\\n            src/finagent/research/streaming_experiment_bridge.py \\\n            scripts/smoke_replay_experiment_campaign.py \\\n            scripts/run_replay_experiment_campaign.py\n',
)
