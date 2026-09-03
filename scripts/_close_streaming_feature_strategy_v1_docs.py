from pathlib import Path

root = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = root / path
    text = target.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise RuntimeError(f"expected one anchor in {path}, found {text.count(old)}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "docs/guides/realtime-source-development-model.md",
    """### Next implementation boundary

The next code increment should build **streaming feature/strategy integration** on top of this source harness rather than adding another provider-specific market-data path. The intended direction is incremental 1m -> 5m/15m/30m streaming aggregation, feature-state updates and existing B0/A0/R1 algorithm invocation through `AlgorithmRunner`, with database replay as the primary U.S. algorithm source and FX live as the connected runtime source. Final target-broker U.S. CFD remains the broker/source freeze surface.
""",
    """## 11. Streaming Feature / Strategy Integration v1 implementation

Streaming Feature / Strategy Integration v1 is implemented as an engineering/runtime capability on top of Streaming Source Harness v1. It does **not** advance `docs/status.toml`, US-D3, B0 research acceptance, A0 Agent Value, R1 Alpha, broker/PAPER, execution or live-capital authority.

Implemented streaming research path:

```text
canonical 1m BarEvent
  -> StreamingBarAggregator
  -> 5m / 15m / 30m StreamingResampledBar
  -> StreamingUSBaselineFeatureEngine (15m signal clock)
  -> StreamingFeatureSnapshot
  -> full-symbol StreamingCrossSectionSnapshot
  -> USBaselineStreamingAlgorithm / AlgorithmRunner
```

The incremental resampler reproduces the accepted US-D2 batch semantics rather than defining a second realtime rule set: the bucket is anchored to the materialized session open, `event_time` is the bucket start, `available_at` is the bucket end, OHLCV uses first/max/min/last/sum, missing minutes remain explicit incomplete coverage, and a session that is not divisible by the requested interval fails closed. Real temporary DuckDB/Parquet regression compares the streaming 15m output field-by-field with `SessionResampledMinuteStore` and binds the same `ResamplingSpec.spec_id`.

The feature engine does not reimplement B0 formulas. It converts completed streaming 15m bars into the existing `USBaselineBar` contract and calls the existing `evaluate_us_baseline_feature()` implementation under the canonical `USBaselineCandidateDenominator`. Cross-sectional state is emitted only when every required symbol has the same event/availability/session/denominator identity; partial symbol denominators never receive a synthetic rank or research result.

A0/R1 statistical authority remains downstream and offline/deterministic. The streaming layer marks its output as B0-compatible engineering evidence but does not recalculate Agent-value, multiplicity, HAC/bootstrap, Alpha or deployment Gates inside the realtime loop.

The delayed-source boundary remains unchanged: canonical/projected market state can observe a progressing delayed source, but `StrategyFreshnessBudget` can prevent those events from reaching the feature algorithm. Quote-only FX input exercises the same `AlgorithmRunner` boundary without manufacturing U.S. OHLCV features.

Deterministic engineering smoke for the frozen 30-minute / two-symbol fixture produced:

```text
B0 denominator        us-baseline-denominator-b8bdb313856e1f7dc652bdd9
replay run            algorithm-streaming-run-fee487ab505bebb2bab5d624
replay semantic state realtime-semantic-state-e2b2c83909b3bb8fd1326fb0
delayed run           algorithm-streaming-run-f7cb9a77852566773c566ba6

input 1m events        60
5m resampled bars      12
15m resampled bars      4
30m resampled bars      2
feature snapshots       4
cross-section snapshots 2
```

The same fixture under the explicit ~900-second delayed timing profile projects all 60 source events but admits zero events to the feature algorithm under the 60-second source-delay / 120-second event-age budget.

### Next implementation boundary

The next coherent increment is **Streaming Research Evidence / Experiment Bridge v1**. It should persist content-addressed streaming feature/cross-section evidence, materialize a deterministic experiment input without recomputing feature authority, and adapt the existing B0/A0/R1 experiment runners to consume that evidence under replay. Database replay remains the primary U.S. algorithm source, FX live remains the connected runtime source, and delayed/current target-CFD timing remains a later broker/source freeze. No live trading or new statistical authority should be introduced by that bridge.
""",
)

replace_once(
    "docs/development/changelog.md",
    """# Changelog

This file records **meaningful completed milestones**, not per-PR implementation detail. Git commits and pull requests are the detailed audit trail; frozen product interpretation belongs in `docs/releases/`.

""",
    """# Changelog

This file records **meaningful completed milestones**, not per-PR implementation detail. Git commits and pull requests are the detailed audit trail; frozen product interpretation belongs in `docs/releases/`.

## 2026-09-03 — Streaming Feature / Strategy Integration v1 implementation closure

- implemented a provider-neutral incremental 1m -> 5m/15m/30m streaming resampler that reuses the accepted US-D2 `ResamplingSpec` semantics: session-open buckets, bucket-start event time, bucket-end availability, deterministic first/max/min/last/sum OHLCV, explicit incomplete coverage and non-divisible-session fail closed;
- proved real temporary DuckDB/Parquet streaming 15m output matches the accepted `SessionResampledMinuteStore` batch path field-by-field and carries the same resampling-spec identity rather than introducing a second realtime aggregation authority;
- implemented content-addressed `StreamingResampledBar`, `StreamingFeatureSnapshot`, `StreamingCrossSectionSnapshot` and `StreamingResearchUpdate` artifacts with engineering-only authority and source-event lineage;
- reused the existing `USBaselineBar`, `canonical_us_baseline_denominator()` and `evaluate_us_baseline_feature()` contracts so the streaming feature path shares the existing B0 candidate/formula identity instead of duplicating feature formulas;
- enforced a full-symbol cross-sectional barrier: partial symbol denominators never emit a cross-sectional snapshot or inferred ranks;
- preserved the delayed-source boundary: all 60 events in the canonical ~900-second delayed fixture remained visible to runtime projection while zero events entered the feature algorithm under the frozen 60-second source-delay / 120-second event-age engineering budget;
- deterministic smoke bound B0 denominator `us-baseline-denominator-b8bdb313856e1f7dc652bdd9`, replay run `algorithm-streaming-run-fee487ab505bebb2bab5d624`, replay semantic state `realtime-semantic-state-e2b2c83909b3bb8fd1326fb0` and delayed run `algorithm-streaming-run-f7cb9a77852566773c566ba6`;
- passed 37 focused streaming/source/US-D2/B0 regressions, deterministic smoke, provider/mutation guards, Ruff, strict mypy, py_compile, Streaming Source Harness, RT replay/projection, generic pytest and project-wide quality checks;
- retained `docs/status.toml` unchanged: this closure proves streaming engineering compatibility only and does not satisfy US-D3, B0/A0/R1 research authority, target-CFD microstructure, PAPER, execution or live-capital acceptance.

""",
)

print("streaming feature strategy v1 completion docs patched")
