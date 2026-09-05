# US-A1 FactorGraph Materialization — A1-1

Issue: #159  
Predecessor: merged A1-0 typed FactorGraph/canonical validation.  
Project stage authority is recorded only in [docs/status.toml](../status.toml).

A1-1 turns the validated declarative graph into deterministic numeric time-series execution while preserving the accepted A0 semantics. It is still pre-Agent infrastructure: no LLM proposal is evaluated financially in this increment.

## 1. Runtime objective

Do not evaluate each candidate as an independent expression tree.

The compiler accepts a batch of validated FactorGraphs and builds one canonical execution DAG:

```text
candidate graphs
      ↓ validate + canonicalize
canonical node execution IDs
      ↓ global deduplication
shared topological execution DAG
      ↓
each unique node series computed once
      ↓
candidate roots map to shared results
```

A graph-local node name never becomes an execution cache key. The cache identity is the canonical structural digest already used by A1 validation.

The compiler records:

```text
naive_node_count
unique_node_count
reused_node_count
reuse_ratio
```

and the materialization report records `node_series_evaluation_count`. For a batch, that count must equal the unique compiled node count rather than the sum of per-candidate graph nodes.

## 2. Determinism before micro-optimization

Legacy parity is an explicit gate. Rolling means and population standard deviations intentionally use the same bounded-window evaluation order as the accepted A0 implementation.

The A1 graph budget caps windows/lookback at 26 bars, so preserving bitwise A0 behavior costs only a small bounded factor. Do not replace these calculations with cumulative approximations merely to reduce arithmetic if doing so changes authoritative floating-point results.

If real profiling later shows rolling-window arithmetic dominates runtime, optimize only with a reviewed numerical-equivalence policy.

## 3. Numeric scopes

A1-1 v1 admits the single-asset time-series subset needed for the accepted A0 family:

```text
INPUT / CONSTANT
LAG
SIMPLE_RETURN / LOG_RETURN
ROLLING_MEAN / STD / MIN / MAX
ADD / SUBTRACT / MULTIPLY
SAFE_DIVIDE
NEGATE
CLIP
```

A1-1 continues to fail closed on these operators when invoked through the original single-asset compiler path:

```text
CROSS_SECTION_RANK
CROSS_SECTION_ZSCORE
WINSORIZE
REGIME_GATE
```

They must not be approximated by a single-asset executor.

A1-2 adds a separately admitted `multi_asset_panel_v1` compiler/materializer path with exact semantics:

```text
CROSS_SECTION_RANK    average percentile rank; ties averaged; asset_id orders traversal
CROSS_SECTION_ZSCORE  population variance; math.fsum accumulation; zero dispersion unavailable
WINSORIZE             deterministic Type-7 lower/upper quantiles
REGIME_GATE           exact reviewed policy ID plus one aligned label per panel bar
```

Every asset must have the same event, availability and session clocks. Asset count and bars per asset are bounded before allocation. The original compiler defaults and serialized identities are unchanged, so A0/R1/R2 evidence does not acquire a new numeric meaning.

The v2 panel kernel applies complete-case availability at every node before its consumers. Incomplete assets cannot affect peer ranks, quantiles or valid breadth. Warm-up is session-local, so joined-session and separate-session outputs/reasons agree. Graphs retain their frozen 15m clock; off-grid/missing clocks at the kernel boundary and non-close availability are rejected. The input adapter may insert explicitly incomplete structural padding for absent rows; those internal sentinel numbers are never usable prices or signals.

Regime masks require a source evidence ID and one aware availability timestamp per label; a future-available label fails closed. Authenticating the underlying classification/evidence lineage remains the caller's admission responsibility. The new output is `finagent.us-a1-factor-panel-materialization.v2`; legacy single-asset evaluation and graph IDs are unchanged.

## 4. Availability semantics

Candidate outputs preserve the accepted first-stage research boundary:

1. insufficient total lookback;
2. same-session window requirement;
3. complete-bar requirement;
4. numeric availability, including explicit safe-division policy.

The materializer returns typed unavailable reasons rather than filling values.

## 5. A0 numeric parity

The focused regression builds all 62 accepted A0 `kind × window` graphs, compiles them together, and evaluates multiple synthetic sessions containing:

- session boundaries;
- incomplete bars;
- a zero-volume reference region;
- a zero-spread close-location bar;
- varying price/volume paths.

For every candidate and every formation point, available A1 values must be **bitwise equal** to `evaluate_us_baseline_feature()` from the accepted A0 implementation. Availability precedence is also compared; A0's `ZERO_REFERENCE_VOLUME` maps to the generic A1 numeric-unavailable denominator terminal.

This closes the structural-only limitation recorded in A1-0 for the legacy grammar.

## 6. Bounded memory and batching

`materialize_compiled_factor_batch()` is deliberately bounded by `maximum_bars_per_batch` (default 10,000). A future corpus materializer should process natural asset/session or asset/partition chunks rather than constructing a dense all-market in-memory cube.

Because the research clock is 15m and the accepted strategy is same-session, normal per-session execution is small; the bound is a fail-safe for future callers.

## 7. Capability increment and next boundary

The repaired panel formulas have synthetic perturbation/composition/partition tests and a label-blind real-data usability operator with independent direct-formula parity. See [the operator guide](us-r3-agent-alpha-expansion.md#offline-feature-usability). These checks do not authenticate a regime source or prove statistical/economic Alpha.

The v1 Agent remains a data-blind proposal control. The active plan additionally specifies a future development-feedback policy and an enforced run/tool boundary. This requires separate identities and acceptance; the realized MANUAL / PROGRAMMATIC / AGENT denominator and selection rule must be frozen before outer/final evaluation.

A1-2 does not change the R2 37-candidate denominator and grants no Alpha, execution, order, PAPER or live-capital authority.
