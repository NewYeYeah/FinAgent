# Replay Experiment Orchestration / Streaming-vs-Batch Research Campaign v1

This guide defines the engineering-only replay campaign that proves the canonical streaming research path and the existing deterministic batch research path consume semantically equivalent U.S. intraday inputs.

`docs/status.toml` remains the sole stage authority. This campaign does **not** close US-D3, certify US-B0, prove Agent Value/Alpha, or grant broker/PAPER/execution/live-capital authority.

## 1. Purpose

The campaign closes the implementation gap between the two already-established research paths:

```text
same bounded 1m U.S. source
        |
        +--> DatabaseReplaySource
        |      -> AlgorithmRunner
        |      -> USBaselineStreamingAlgorithm
        |      -> StreamingResampledBar / FeatureSnapshot / CrossSectionSnapshot
        |      -> StreamingResearchEvidenceBundle
        |
        +--> CalendarSessionizedMinuteStore
               -> SessionResampledMinuteStore
               -> SameSessionLabelStore
               -> existing B0 / A0 / R1 materializers
```

The campaign does not compare approximate performance metrics. It canonicalizes each semantic surface and requires exact row count plus SHA-256 digest equality.

## 2. Authority boundary

The formal `scripts/materialize_us_b0_baselines.py` operator remains separately stage-gated and is not called by this campaign. That formal operator continues to require accepted US-D3 evidence and `docs/status.toml` authority before a formal US-B0 run may occur.

The replay campaign instead uses the same lower-level deterministic contracts for engineering parity only:

```text
engineering_only            = true
certification_authority      = false
research_authority           = false
agent_value_gate_authority   = false
alpha_authority              = false
execution_authority          = false
stage_exit_authority         = false
```

A green campaign therefore means “streaming and batch semantics agree for this bounded input,” not “the research result is accepted.”

## 3. Frozen parity surfaces

The v1 campaign requires five independent batch row slices:

```text
5m  / 60m label
15m / 30m label
15m / 60m label
15m / 120m label
30m / 60m label
```

It then requires exact parity for sixteen surfaces:

```text
rows:5m:60m
rows:15m:30m
rows:15m:60m
rows:15m:120m
rows:30m:60m

b0:observations
b0:materialization-diagnostics
b0:evaluation

a0:observations
a0:materialization-diagnostics

r1:TRAIN:15m:60m
r1:EVALUATION:5m:60m
r1:EVALUATION:15m:30m
r1:EVALUATION:15m:60m
r1:EVALUATION:15m:120m
r1:EVALUATION:30m:60m
```

No tolerance is used. A missing row, duplicate row, clock difference, feature difference, label difference, denominator mismatch, or evaluation difference changes the canonical digest and fails the corresponding parity check.

## 4. Label clock correction discovered by the campaign

The campaign exposed an important distinction that fixture-only bridge testing could not observe.

For a completed 15-minute bar covering 14:30–14:45:

```text
bar / feature formation event_time = 14:30
bar available_at                    = 14:45
D2 label source_event_time          = 14:44
D2 label source_available_at        = 14:45
```

The first clock identifies the resampled feature formation. The second identifies the raw 1-minute close used as the same-session label price anchor.

`StreamingExperimentLabel` therefore preserves two concepts:

```text
source_event_time   feature/bar formation clock used to bind persisted resampled evidence
price_event_time    optional D2 raw 1m price-source event clock
source_available_at common PIT join clock
```

When `price_event_time` exists it must be exactly one minute before `source_available_at`. Persisted experiment rows expose the D2 price-source clock, while bundle validation continues to bind the label to the correct resampled formation. Old bridge v1 fixture documents that do not carry `price_event_time` remain readable and retain their previous identity semantics.

## 5. Deterministic fixture mode

CI uses `ReplayCampaignSourceScope.FIXTURE` over a real temporary DuckDB/Parquet minute store. The same file is queried independently by replay and batch paths.

The fixture verifies:

- true DuckDB/Parquet query execution rather than mocked row lists;
- session-aware 5m/15m/30m resampling;
- independent 30m/60m/120m same-session labels;
- exact B0 persisted-feature parity;
- A0 delegation to the existing shared materializer;
- R1 train/OOS slice delegation;
- write-once campaign report behavior;
- bounded-row fail-closed behavior;
- canonical B0 denominator enforcement;
- provider/broker-mutation and authority guards;
- Ruff, strict mypy and Python compilation.

## 6. Local bounded mode

`scripts/run_replay_experiment_campaign.py` runs the same campaign against the admitted local U.S. minute snapshot. It binds the frozen local source identities directly:

```text
source revision  776328445b7ac6e7815ef3a483e9c8ded1eb6d56
inventory        us-minute-inventory-c2cbf682b456f97eb613ed65
cleaning stack   us-minute-cleaning-stack-a0d745a4a75d25a63e3a8244
calendar         trading-calendar-03a9c29f566d6634aedbbbdc
```

The operator accepts only the bounded symbol set and time window as research-data choices. It does not load a pending final EngineeringUniverse or fabricate US-D3 certification.

Example from the existing Conda workstation environment:

```powershell
conda activate finagent
python scripts/run_replay_experiment_campaign.py D:\path\to\OHLCV-1m `
  --symbols AMD,INTC,MSFT,NVDA `
  --start 2026-01-05T14:30:00+00:00 `
  --end 2026-01-05T21:00:00+00:00 `
  --report-output reports\replay_experiment_campaign\seed_2026-01-05.json
```

Choose a window actually present in the local snapshot. The operator fails before Python row materialization if any independent batch plan exceeds `--maximum-batch-rows`; do not increase the bound merely to force a pass without reviewing memory/runtime implications.

A successful local report explicitly records:

```text
formal_us_b0_operator_invoked = false
us_d3_certification_consumed  = false
```

The report may be useful as real-values engineering evidence, but it cannot substitute for the active US-D3 delayed-reference/final-universe/reconciliation evidence chain.

## 7. Failure interpretation

A red campaign is an implementation discrepancy, not a reason to weaken the research protocol.

Typical failure classes are:

```text
rows:*             resampling / PIT clock / label-row mismatch
b0:observations    persisted feature or label-admission mismatch
b0:evaluation      downstream B0 evaluator receives non-equivalent observations
A0 mismatch        shared candidate materialization boundary diverged
R1 mismatch        frequency/horizon slice or formation semantics diverged
```

Fix the source, resampling, evidence, or bridge implementation. Do not relax equality, remove a slice, alter D2 label semantics, reduce the denominator, or bypass the formal stage guard.

## 8. Next implementation boundary

After v1 closure, the next coherent engineering increment is **Bounded Real-Data Replay Campaign / Runtime Soak v1**:

1. run `LOCAL_BOUNDED` on representative real U.S. historical slices and multiple accepted seed/candidate symbol sets;
2. persist campaign reports and runtime/resource diagnostics as engineering evidence;
3. add restart/replay determinism and longer-session soak coverage;
4. exercise the same campaign orchestration under accelerated and step pacing without changing semantic identities;
5. keep target-broker CFD, current-market timing, formal US-B0/A0/R1 acceptance and stage advancement separately governed.

This remains subordinate to the active `docs/status.toml` US-D3 evidence gate.
