# US-A1 FactorGraph DSL — A1-0 Contracts

Issue: #159  
Entry authority: `docs/status.toml` remains `US-R1 / accepted_no_robust_factor_family_terminal`, with `next_stage = "research iteration"`.

US-A1 responds to the accepted A0 negative Agent-value result by increasing **research expressiveness and falsifiability**, not by increasing LLM call count. A1-0 is contract infrastructure only: it does not call an LLM, evaluate financial performance, modify the R2 denominator, or grant Alpha/execution authority.

## 1. Separation from US-R2

The first US-R2 replication remains denominator-preserving:

```text
R2 first replication denominator = accepted US-R1 37 candidates
new A1 candidates admitted        = false
performance filtering             = false
```

A1 may develop in parallel, but no A1-generated candidate may enter that first R2 replication. This keeps the regime/time-coverage question identifiable.

## 2. FactorGraph boundary

The Agent-facing representation is a typed declarative DAG:

```text
FactorGraphSpec
  ├─ FactorNode(INPUT / CONSTANT)
  ├─ lag / return / rolling transforms
  ├─ bounded arithmetic composition
  ├─ cross-sectional rank / z-score
  ├─ clip / winsorize
  └─ explicitly bound regime gate
```

The LLM does **not** receive authority to emit executable Python, SQL, shell, provider calls or label access. A graph is data. FinAgent validates and later materializes it with deterministic project code.

US-A1 v1 preserves the accepted research semantics:

```text
signal clock          15m
price basis           RAW
availability          available_at
history               same-session only
formation bars        complete only
inputs                 open/high/low/close/volume only
```

## 3. Type and unit rules

Nodes carry inferred semantic units and scope:

```text
PRICE
VOLUME
DIMENSIONLESS

TIME_SERIES
CROSS_SECTIONAL
```

Examples:

- `SIMPLE_RETURN(PRICE)` and `LOG_RETURN(PRICE)` -> `DIMENSIONLESS`;
- add/subtract require identical semantic type and scope;
- multiply is admitted only when at least one operand is dimensionless;
- divide supports equal units -> dimensionless, or division by a dimensionless denominator;
- final factor output must be dimensionless;
- cross-sectional rank/z-score make the output cross-sectional.

Unsupported unit combinations fail closed rather than being silently coerced.

## 4. Explicit unsafe-denominator policy

Every `SAFE_DIVIDE` node must declare a zero/near-zero denominator policy:

```text
UNAVAILABLE
CONSTANT(fallback_value)
```

This is required to represent legacy semantics such as close-location's zero-spread fallback without hidden implementation behavior.

## 5. Complexity budget

A1 graphs have a frozen bounded complexity surface. The initial defaults are:

```text
max nodes          32
max edges          48
max graph depth     8
max operator window 26 bars
max total lookback  26 bars
max regime gates     2
```

The limits are not evidence that a graph is statistically valid. They bound search complexity, runtime and reviewability.

## 6. Fail-closed validation and canonical identity

`validate_factor_graph()` performs:

```text
node/edge budget check
        ↓
parameter + arity validation
        ↓
missing-reference / unused-node check
        ↓
cycle detection + deterministic topological order
        ↓
one-pass type/scope/lookback/depth inference
        ↓
canonical structural hashing
```

Malformed LLM output returns blockers. Missing windows, lags or denominator policies must never trigger internal assertions or partially execute.

There are two identities:

- `proposal_graph_id`: exact submitted syntax, including local node names/order;
- canonical `candidate_id`: semantic graph identity after canonicalization.

Local node IDs and storage order do not affect `candidate_id`. `ADD` and `MULTIPLY` canonicalize child order. Canonically duplicated subexpressions are rejected in A1-0 rather than allowing redundant graph work.

## 7. Runtime design

Validation is implemented over a flat DAG with hash maps, reachability traversal and Kahn topological sorting. Each reachable node is inferred once.

Expected validation complexity is approximately:

```text
O(V + E) + bounded child sorting for commutative nodes
```

A1-1 should preserve this structure and compile canonical subexpressions once. The canonical node digest is intentionally suitable as a common-subexpression cache key so a batch of related Agent candidates does not repeatedly recompute the same rolling/return transform.

Do not implement A1-1 as independent recursive evaluation of every candidate tree.

## 8. A0 compatibility boundary

`legacy_a0_candidate_factor_graph()` provides a structural representation for all 62 accepted A0 `kind × window` candidates:

```text
reversal
momentum
range_mean
return_volatility
volume_surprise
close_location
```

A1-0 checks that every legacy candidate maps to a valid, unique canonical graph with the same required input fields and total lookback bars.

This is **structural compatibility only**. A1-1 must implement the deterministic materializer and prove numerical parity with the accepted A0 formulas before any A1 Agent proposal is evaluated financially.

## 9. Regime gates

A `REGIME_GATE` is invalid unless the graph binds an explicit admitted `regime_policy_id`. A1 does not let the Agent invent an unreviewed regime label from candidate performance.

Regime classification remains governed by the separately reviewed R2 regime policy and must use ex-ante observable information only.

## 10. Hypothesis and falsification metadata

A candidate may carry bounded structured metadata:

```text
mechanism category
expected direction
expected regime scope
required inputs
falsification criteria
invalidating conditions
parent candidate IDs
```

This is intentionally not hidden chain-of-thought. The project stores auditable research claims and falsification conditions, not private reasoning traces.

## 11. A1-1 and later work

After A1-0 merges:

1. implement a deterministic graph materializer/compiler;
2. reuse canonical subexpression work across candidates;
3. prove exact/defined-tolerance parity for all 62 A0 structures;
4. add cross-sectional and composed-feature synthetic tests;
5. only then add an Agent proposal/repair adapter;
6. preregister a controlled MANUAL / PROGRAMMATIC / AGENT pilot before financial results are inspected.

The pilot keeps equal candidate-slot budgets and multiple independent Agent runs. Structural novelty alone is not sufficient for an Agent Value Gate pass.

No A1-0/A1-1 artifact grants Alpha, execution, order, PAPER or live-capital authority, and `docs/status.toml` remains unchanged.
