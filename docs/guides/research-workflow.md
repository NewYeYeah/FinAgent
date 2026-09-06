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

The first adaptive MarketState model should be simple and causal. Use the existing R2 four-state rule as a benchmark and a scikit-learn GMM as the first probabilistic candidate unless a stronger reason is documented.

Fit every scaler/model/threshold inside the allowed training/development chronology. Persist enough information to reproduce state probability at each formation time.

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
