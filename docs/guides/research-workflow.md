# Research workflow

This guide describes how to work with the active research architecture without duplicating stage-specific implementation history.

## 1. Start from stage intent

Read:

1. [`../status.toml`](../status.toml);
2. [`../development/current-plan.md`](../development/current-plan.md);
3. the current stage plan.

For current R3/R4 work, inspect existing `src/finagent/research/us_a1_*`, `src/finagent/research/us_r3_*` and `src/finagent/agents/r3_*` code/tests before proposing another research runtime.

## 2. Research loop

The intended R4 loop is:

```text
objective
→ inspect prior evidence / literature / MarketState / FactorLibrary
→ propose hypothesis or factor-set/allocator change
→ deterministic validation/evaluation
→ explicit result
→ Agent critique/decision
→ next bounded experiment
→ freeze candidate or stop
```

The Agent chooses development research actions. Deterministic code computes metrics and enforces the admitted scope/budget.

## 3. Factor representation

Use typed FactorGraph for ordinary formula factors.

Do not replace it with arbitrary model-generated Python merely to gain expressiveness. If a mechanism cannot be represented, first decide whether it is actually:

- a new factor operator;
- a MarketState feature;
- an allocation/exposure rule;
- a portfolio/execution mechanism.

Only the first category necessarily belongs in FactorGraph.

## 4. Development feedback

Development feedback is allowed in R4 but must be treated as adaptive exposure.

Keep:

- exact trial identity;
- failed/invalid/repaired/duplicate attempts;
- evaluator calls;
- model/provider identity;
- tokens/cost/time budget;
- explicit Agent decision after each result.

Do not discard poor trials because they are inconvenient for Agent-value accounting.

## 5. MarketState

The first adaptive MarketState is implemented with train-only StandardScaler and
[scikit-learn GaussianMixture](https://scikit-learn.org/stable/modules/generated/sklearn.mixture.GaussianMixture.html).
The existing R2 four-state IWM rule remains available as the deterministic comparator.

Install `uv sync --frozen --extra dev --extra adaptive-research`. Run
`python scripts/run_r4_research_slice.py run --help` for the full command. Supply
existing local R2 base Parquet, calendar, plan and passed evidence paths, source
ID/revision, an explicit comma-separated universe, and aware `--fit-start`,
`--fit-end`, `--evaluation-start`, `--evaluation-end` timestamps. Each window must
include complete calendar sessions, fit must finish before evaluation, and both
windows must fit the single annual source artifact. Default proxy is IWM; the
universe must contain it. Default breadth/top-count is 20/5; small synthetic
fixtures must declare their smaller breadth/count explicitly.

The CLI registers three existing R3 prototypes with their prior no-confirmed-Alpha
terminal in provenance, performs no candidate search, and leaves them TESTING.
`--output` receives `request.json`, `market_state_model.json`, `result.json` and
`factor_library.sqlite`; unsuccessful fitting preserves `failure.json` and the
original request. Use a new output directory for a changed request, input or
implementation. Repeating identical inputs reproduces the result and does not
duplicate registry evaluations (it currently recomputes the bounded slice).

Inspect without mutation:

```bash
python scripts/run_r4_research_slice.py inspect --library <output>/factor_library.sqlite
python scripts/run_r4_research_slice.py inspect --library <output>/factor_library.sqlite --factor <candidate-id>
```

`--factor` inspection also supports an aware `--as-of` cutoff. Result files contain
global and soft-state-weighted coverage, signal-target turnover, 15m/60m RankIC
decay and rank similarity. Economic diagnostics separately apply each fixed argmax
state as an entry gate under the full 0/1/5/10 bps grid, with delayed entries and
ungated exits. These scenarios are hypothetical costs, not measured broker fills.
Missing entire sessions invalidate economic NAV rather than disappearing or
becoming a successful cash day. Missing labels reduce the reported observation
weight without changing formation coverage. These are development diagnostics,
not evidence that MarketState adds value or that Alpha/PAPER/live is accepted.

## 6. Factor allocation

Compare Agent behavior to strong deterministic baselines before attributing value to the LLM.

Expected baseline families:

```text
EqualWeight
RollingICWeight
RollingNetReturnWeight
RegimeConditionalWeight
regularized linear/meta allocator
```

Agent may select among admitted factors/allocators and request bounded parameter experiments. Final R5 criteria remain outside Agent control.

## 7. Exploration versus confirmation

R4 result:

```text
candidate strategy or NO_ADAPTIVE_CANDIDATE
development evidence only
```

R5 result:

```text
CONFIRMED / REJECTED / INSUFFICIENT_INDEPENDENT_EVIDENCE
```

Never describe an adaptively optimized R4 development result as independent Alpha evidence.

## 8. Research Console

During R4, expose only what is needed to understand/control the loop:

- objective;
- Agent actions/tool calls;
- experiment result cards;
- current MarketState;
- selected factor set/allocator;
- remaining budget;
- explicit next decision.

The full Workbench 2.0 productization is a later stage.
