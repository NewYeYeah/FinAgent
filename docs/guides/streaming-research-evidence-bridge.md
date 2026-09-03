# Streaming Research Evidence / Experiment Bridge v1

This guide records the implementation boundary between provider-neutral streaming research output and the existing U.S. B0/A0/R1 experiment stack.

`docs/status.toml` remains the only stage authority. This bridge is implementation/development infrastructure only; it does not certify US-D3, B0, A0, R1, CFD execution, PAPER, live-current market data, or live capital.

## 1. Purpose

The streaming runtime now produces incremental 5m/15m/30m resampled bars, B0-compatible feature snapshots and full-denominator cross-section snapshots. The bridge persists those outputs as immutable experiment evidence and maps them into existing research materializers without creating a second statistical implementation.

```text
DatabaseReplaySource / canonical stream
        -> StreamingBarAggregator
        -> StreamingUSBaselineFeatureEngine
        -> StreamingResearchUpdate
        -> StreamingResearchEvidenceBundle
        -> content-addressed persisted artifact
             |-> US-B0 observations
             |-> US-A0 existing materializer
             `-> US-R1 existing materializer
```

The bridge is not a research Gate. Existing B0/A0/R1 runners retain all downstream statistical and acceptance authority.

## 2. Evidence contract

`StreamingResearchEvidenceBundle` binds:

- source `AlgorithmRunReport` identity;
- feed profile and subscription identities;
- streaming update identities;
- canonical US-B0 denominator identity and required-symbol denominator;
- complete persisted 5m/15m/30m `StreamingResampledBar` evidence;
- B0-compatible `StreamingFeatureSnapshot` evidence;
- full-symbol `StreamingCrossSectionSnapshot` evidence;
- explicit `StreamingExperimentLabel` maturity evidence.

Artifact persistence stores the complete nested bundle, SHA-256 of the serialized bytes, byte count, bundle identity and artifact identity. Reads validate both the outer byte digest and the nested content-addressed identities; recomputing only the outer SHA does not make tampered nested evidence valid.

## 3. Fail-closed rules

Experiment evidence is rejected when any of the following is observed:

```text
partial required-symbol feature denominator
conflicting/duplicate resampled-bar semantic key
duplicate feature identity or duplicate symbol in one formation
cross-section/feature membership mismatch
missing resampled-bar backing for a feature or label
bar/feature/label clock mismatch
session mismatch
label source-price mismatch
duplicate label semantic key
unsupported signal interval or label horizon
invalid label maturity/unavailable-reason semantics
artifact SHA/size/bundle identity mismatch
nested content-addressed identity mismatch
```

No missing observations are silently synthesized and no partial cross-section is promoted into a research denominator.

## 4. B0 bridge

The B0 path consumes persisted `USBaselineFeatureEvaluation` values carried by streaming feature snapshots. It does not call the feature evaluator again to recreate feature values.

The existing `USBaselineRunSpec`, canonical B0 denominator, observation contract and evaluation/report logic remain unchanged. Therefore the bridge can prove streaming-versus-batch input parity without becoming a new B0 formula authority.

## 5. A0 and R1 bridges

A0 and R1 require candidate-specific feature evaluation and label slices beyond the canonical B0 snapshot values. For those paths the bridge converts persisted resampled bars plus explicit labels into the existing materializer row contract and delegates to the existing A0/R1 materializers.

The bridge does **not** compute or approve:

```text
Agent candidate generation authority
Agent Value statistics or Gate decisions
multiple-testing authority
HAC/bootstrap authority
R1 robust Alpha statistics or Gate decisions
execution/PAPER/live authority
```

Those remain exclusively in the existing governed research/evaluation layers.

## 6. Deterministic smoke fixture

The frozen engineering smoke uses a two-symbol, 60-minute XNYS-like fixture and expects:

```text
resampled bars          36
feature snapshots        8
cross-section snapshots  4
explicit labels         52
B0 observations         64
A0 observations          8
R1 observations         24
```

Round-trip bundle identity must be exact and all B0/A0/R1 materialization diagnostics must pass. The fixture explicitly reports all research, Agent-value, Alpha, execution and stage-exit authority flags as false.

These counts are deterministic engineering evidence only; the synthetic fixture is not market evidence and does not satisfy any research acceptance threshold.

## 7. Validation boundary

The dedicated `streaming-research-evidence-bridge-v1` workflow runs:

- bridge regressions including artifact/tamper/denominator tests;
- Streaming Feature / Strategy Integration regressions;
- Streaming Source Harness regressions;
- existing US-B0 materialization/evaluation regressions;
- existing US-A0 evaluation-bridge regressions;
- existing US-R1 materialization regressions;
- deterministic bridge smoke;
- provider/broker-mutation and authority-escalation guards;
- Ruff, strict mypy and `py_compile` for the new bridge/smoke surfaces.

The project-wide PR test/quality workflow remains an independent second gate.

## 8. Development/freeze relationship

The source roles remain unchanged:

```text
DEV-REPLAY   local real U.S. historical data -> streaming algorithm/research development
DEV-LIVE     FX MT5 current feed              -> connected transport/runtime validation
DEGRADED     delayed feed profile             -> timing/fail-closed validation
FINAL-FREEZE target-broker U.S. CFD           -> final market/broker/execution freeze
```

FX evidence never substitutes for U.S. research semantics. Historical replay supplies real historical U.S. market values and real streaming execution semantics, but not a current market feed. Target-CFD broker-specific semantics remain deferred to the final freeze campaign.

## 9. Follow-on campaign

**Replay Experiment Orchestration / Streaming-vs-Batch Research Campaign v1** is now implemented. It independently materializes accepted US-D2 batch bars/labels from the same bounded minute source used by `DatabaseReplaySource`, freezes streaming evidence, and requires exact canonical equality across five row slices plus B0/A0/R1 materialization/evaluation surfaces. The implementation also separates the feature-formation clock from the D2 raw 1m price-source clock in persisted label evidence.

See `docs/guides/replay-experiment-campaign.md` for the frozen sixteen parity surfaces, deterministic fixture identities, local bounded operator and authority boundary.

The next coherent engineering increment is **Bounded Real-Data Replay Campaign / Runtime Soak v1**. It remains implementation/evidence preparation until current stage authority explicitly permits formal downstream research acceptance.
