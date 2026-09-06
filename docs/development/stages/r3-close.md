# R3-CLOSE — close the current Agent/Alpha expansion

## Goal

End R3 as an exploratory **workflow-verified / no-confirmed-Alpha** stage and preserve only the reusable capabilities needed by R4. Do not continue formula mining on the exposed R3 development data.

## Current baseline

The active R3 branch (PR #174) contains:

- multi-asset FactorGraph panel materialization/usability checks;
- a small executable OHLCV alpha prototype catalog;
- economic development evaluation with cost/delay assumptions;
- completion/follow-up/inference/confirmation support code;
- a v2 Agent capability runtime with typed JSON actions;
- SQLite run/slot/attempt/evaluation/token/cost/time accounting;
- bounded development feedback and run-local memory;
- offline adversarial/resume tests;
- real guided workflow repair experiments.

The financial result remains negative at the primary R3 development assumption: the complete pilot selected cash in all 12 runs at 5 bps. Guided tool-use success is not evidence of autonomous research superiority or profitability.

## Deliverables

1. Stop adding new R3 financial hypotheses and ad-hoc exposed-data screens.
2. Keep the reusable implementations that R4 will call:
   - FactorGraph validation/materialization;
   - development economic evaluator;
   - R3 Agent contracts/runtime/ledger or their consolidated equivalents;
   - provider adapter path that can be admitted for R4;
   - focused tests proving numerical and budget/tool boundaries.
3. Remove or clearly demote code/documentation whose only purpose is to continue the old R3 campaign if it obstructs the R4 interface. Cleanup may be deferred to the first R4 PR when direct deletion would create unnecessary merge risk.
4. Record R3 as `WORKFLOW_VERIFIED_NO_CONFIRMED_ALPHA` in project status/history.
5. Ensure the current documentation tree and active branch agree about the next stage.

## Reuse plan

Do not create:

- a third Agent runtime;
- a new factor DSL;
- a new data plane;
- a new statistical framework.

R4 is expected to build on `src/finagent/agents/r3_*`, the current FactorGraph path and the existing economic evaluator, consolidating names later only when a stable general abstraction is clear.

## Non-goals

- independent Alpha confirmation;
- more factor sweeps on 2025/R2 exposed periods;
- Workbench 2.0 redesign;
- PAPER or broker mutation;
- Tick/LOB research;
- declaring the real-provider path globally sandboxed.

Independent/prospective confirmation is deliberately moved to R5 rather than used as a reason to keep R3 open indefinitely.

## Suggested PR boundary

R3 closeout should normally be one merge/cleanup action around the existing PR. A separate cleanup PR is justified only if it materially reduces risk or removes dead complexity without changing research semantics.

## Exit gate

R3-CLOSE passes when:

```text
R3 reusable code is landed on the target branch/main
relevant FactorGraph / evaluator / Agent runtime tests pass
no unresolved R3 code path claims Alpha or PAPER authority
R3 result is recorded as no-confirmed-Alpha
status.toml points to R4-AGENT-ADAPTIVE
```

Failure to find Alpha is not a stage failure. Continuing to search the same exposed data is not an acceptable substitute for closing the stage.
