# R5-INDEPENDENT-CONFIRMATION — confirm the complete adaptive algorithm

## Goal

Determine whether the complete strategy produced by R4 survives genuinely independent evidence after the research loop, market-state model, factor rules and allocator are frozen.

R5 is the first stage allowed to make a **confirmed Alpha** claim for the adaptive program.

## Preconditions

- R4 has produced an `AdaptiveStrategy` candidate rather than only development experiments;
- all R4-exposed data and experiment history are identified;
- the strategy can run without Agent access to R5 outcomes;
- cost/execution assumptions for the confirmation are frozen before returns are opened.

If these conditions cannot be met, return `INSUFFICIENT_INDEPENDENT_EVIDENCE` rather than manufacturing a holdout.

## Deliverables

### 1. AdaptiveStrategySpec

Freeze the entire algorithm, not only a factor list:

```text
research/data/universe identity
MarketState feature/model/fitting rule
FactorLibrary version
factor inclusion/retirement rule
allocator family and parameters
Agent role at inference time, if any
update/refit cadence
signal and execution clock
cash/gross-exposure rule
cost/slippage assumptions
risk/portfolio constraints
missing-data behavior
stopping/failure behavior
```

Any change that can alter decisions creates a new spec/version and invalidates the unopened confirmation run for the old spec.

### 2. Independent evidence admission

Prefer, in order:

1. prospective market observations arriving after strategy/protocol freeze;
2. a demonstrably sealed chronological segment not exposed to R4 or model/pretraining-specific research decisions;
3. another independently sourced dataset only when it contains genuinely independent observations, not merely the same dates/prices under a different provider name.

Record known LLM parametric look-ahead risk as a limitation where historically famous outcomes may be encoded in model training. It does not replace prospective confirmation.

### 3. Confirmation protocol

Pre-register:

- primary economic endpoint;
- secondary diagnostics;
- cost and delay scenarios;
- minimum observation/power or an explicit finite evidence limit;
- multiplicity procedure for the actual frozen family of strategies/endpoints;
- stopping rule;
- allowed missing-data handling;
- what constitutes CONFIRMED, REJECTED or INSUFFICIENT.

Use chronology-aware inference: HAC/block/session resampling and purge/embargo where the holding/label structure requires it.

### 4. Result

Terminal states:

```text
CONFIRMED
REJECTED
INSUFFICIENT_INDEPENDENT_EVIDENCE
```

A rejected/insufficient result may start a **new versioned R4 cycle**, but the R5 evidence must not be fed back into the same frozen strategy and still called independent.

## Agent boundary

During R5 the Agent may:

- explain the frozen spec;
- generate presentation/diagnostic summaries after the terminal result is fixed;
- inspect already-public confirmation outputs.

The Agent may not:

- alter factors/allocator/model based on R5 returns;
- choose which R5 observations count after seeing performance;
- change costs/gates/stopping rules;
- open hidden/sealed returns before the frozen evaluator does.

## Reuse plan

Reuse the existing statistical/economic primitives where they match the frozen endpoint. Do not recreate R1/R2's many materialization stages solely for lineage aesthetics. Add only the minimal runner/evidence boundary needed to keep the final evaluation independent and reproducible.

## Non-goals

- Workbench redesign;
- PAPER execution;
- live parameter tuning;
- new factor search;
- broker-order authority.

## Suggested PR slices

Usually 1–2 coherent increments:

1. freeze/admission/runner and dry-run contract;
2. independent/prospective execution and terminal evidence when real data is available.

The real evidence run may be an operator action rather than another code PR.

## Exit gate

R5 exits when one frozen `AdaptiveStrategySpec` has a terminal independent result and the result can be reproduced from its admitted inputs.

Only `CONFIRMED` makes that spec eligible for the PAPER-TRADING stage. WORKBENCH-2 may still proceed after REJECTED/INSUFFICIENT because the research workstation remains useful for the next R4 cycle.
