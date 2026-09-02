# US-A0 controlled Agent incremental-value experiment

US-A0 answers a narrower question than the later Alpha Gate:

```text
Does the Agent add measurable research value versus fixed MANUAL and bounded PROGRAMMATIC search
under the same data, vocabulary, trial budget and split-bound evaluation evidence?
```

It does **not** ask whether any candidate is deployable. Agent Value Gate and Alpha Gate remain separate.

## Current authority boundary

The repository may preregister US-A0 contracts while the project-stage authority still reports US-D3 and while US-B0 real-data evidence is pending. Formal Agent-value execution is not authorized until:

```text
US-I0 active-session acceptance completed
MT5-D0 reconciliation accepted
US-D3 accepted
US-B0 real folds executed
US-B0 split-bound evidence graph accepted
project stage advanced through US-B0 to US-A0
```

The current continuous-market FX smoke is engineering evidence only and cannot be supplied as an A0 predecessor.

## Frozen preregistration identities

The PILOT and FORMAL bundles were frozen before any real A0 result inspection. Their deterministic identities are now golden regression expectations:

```text
shared vocabulary
us-agent-value-vocabulary-a25485cf3c63c1c4ffd3bbc4

PILOT protocol
us-agent-value-experiment-protocol-d8b568d76dfa994b2711aa03

PILOT bundle
us-agent-value-preregistration-9d592189de4ed0edf16e23c6

FORMAL protocol
us-agent-value-experiment-protocol-d214ae1745ebf76284ec1887

FORMAL bundle
us-agent-value-preregistration-06af38db5c1a22c2e8a3cd64
```

A future intentional protocol revision must create new identities. It may not silently mutate these frozen artifacts after results exist.

## Shared structural vocabulary

All three arms propose from the same bounded grammar. No arm may emit executable Python, SQL, arbitrary expressions or hidden feature code.

Frozen primitive kinds:

```text
reversal
momentum
range_mean
return_volatility
volume_surprise
close_location
```

The grammar preserves the accepted US-B0 semantics:

```text
signal clock       15m
label              same-session 60 trading-minute RAW simple return
formation clock    available_at
price basis        RAW
history            same session only
bars               completed bars only
```

Window domains are frozen before result inspection:

```text
reversal / momentum / return_volatility / volume_surprise: 2..13 bars
range_mean:                                                   1..13 bars
close_location:                                               exactly 1 bar
```

Input fields are derived from primitive kind, not chosen by the generator. The resulting structural space contains exactly 62 candidate formulas.

A candidate identity is based on its structural formula and vocabulary identity. Hypothesis wording is deliberately excluded, so an Agent cannot create artificial novelty by describing the same formula differently.

## MANUAL arm

The MANUAL arm is frozen now, before A0 results exist.

- first 8 formulas structurally reproduce the existing US-B0 MANUAL denominator;
- PILOT uses a fixed 16-formula grid;
- FORMAL uses a fixed 32-formula grid;
- the additional formulas are a preregistered coverage grid over the same grammar, not performance-selected extensions.

MANUAL cannot repair or replace a slot.

## Shared trial budget and repair semantics

Budget is per independent run:

```text
PILOT   16 candidate slots / run
FORMAL  32 candidate slots / run
```

Independent-run requirements:

```text
              PILOT   FORMAL
MANUAL           1       1
PROGRAMMATIC     1      >=3
AGENT            1      >=3
```

For PROGRAMMATIC formal runs, seeds must be recorded and distinct. The initial PROGRAMMATIC generator is seeded uniform sampling without replacement from the exact 62-formula vocabulary.

For every arm, a slot is the trial-budget unit. An invalid or duplicate initial proposal consumes that slot. At most one repair attempt is allowed inside the consumed slot. A repair does not create a new slot. Replacement slots are forbidden in v1.

This prevents an Agent from obtaining a larger effective search budget through repeated retries.

## Agent metadata and reasoning boundary

Every AGENT run binds:

```text
provider_id
model_id
prompt_template_id
generator_id
run_ordinal
```

Every Agent proposal or repair attempt records:

```text
llm_calls
input_tokens
output_tokens
latency_ms
cost_usd
generated_at
```

Stored proposal content is limited to structured formula fields and a short hypothesis summary. Hidden chain-of-thought is neither required nor stored.

Optional `parent_candidate_id` records explicit discovery evolution when a structured proposal is derived from a previously accepted candidate. A parent must already have been accepted in that run.

## Evidence contracts

The A0 contract layer includes:

```text
USAgentValuePrimitiveVocabulary
USAgentValueCandidateSpec
USAgentValueExperimentProtocol
CandidateGenerationRunSpec
CandidateGenerationEvent
CandidateGenerationRun
USAgentValueEvaluationDenominator
USAgentValueEvaluationBinding
USAgentValueFoldExecutionSpec
USAgentValueFoldEvaluationReport
USAgentValueRunEvaluationReport
RunEvaluationLink
SearchArmResult
AgentValueExperiment
```

`RunEvaluationLink` is intentionally a link/summary boundary. OOS RankIC or worst-fold metrics must come from authoritative split-bound evaluation evidence; the A0 experiment layer does not read row-level returns and recompute them.

`SearchArmResult` may derive generation efficiency metrics such as valid-candidate, invalid, duplicate, repair and LLM-cost rates. Structural novelty is derived only from content-addressed candidate IDs.

`AgentValueExperiment` does not automatically declare a winner. Even when all evidence is complete:

```text
agent_value_gate_decision = UNDECIDED_REQUIRES_SEPARATE_REVIEW
agent_value_gate_authority = false
alpha_authority = false
```

A later increment must bind a separately reviewed Agent Value Gate; no threshold is invented merely to make the current harness pass.

## Shared evaluation bridge

Every completed generation run is compiled into an A0-owned evaluation denominator containing only the run's final `VALID_UNIQUE` structural candidates. Invalid and duplicate slots remain visible in generation evidence and still consume the frozen trial budget; they are never replaced merely to obtain a full financial denominator.

The evaluation binding copies the accepted US-B0 statistical and data authority into the A0 run:

```text
same US-D3 certification report
same certification outcome
same EngineeringUniverse
same 15m signal clock
same same-session 60m RAW label
same minimum cross-section / evaluated-period / IC-period gates
```

Only the denominator identity changes to the content-addressed A0 generation-run denominator.

Feature formation and label admission reuse the existing US-B0 materializer implementation. The A0 adapter does not construct or serialize a fake MANUAL denominator; the Python cast at this boundary exists only because the frozen B0 materializer's nominal annotation predates A0 and its runtime implementation consumes the shared `protocol` / `candidates` structural surface.

Candidate statistics are evaluated through the same `evaluate_us_baseline_candidate()` core. A0 creates its own fold/run evidence schemas so the resulting reports do not falsely claim to be pre-Agent MANUAL baseline evidence.

The experiment phase is an explicit content-addressed field on the evaluation binding and fold execution specs. A FORMAL run remains FORMAL even if invalid/duplicate generation leaves fewer than 16 accepted candidates; phase is never inferred from observed candidate count or performance.

A run with zero accepted candidates is a valid experiment outcome:

```text
status = NO_ACCEPTED_CANDIDATES
evaluated_candidate_count = 0
valid_candidate_count = 0
best_mean_rank_ic = null
best_worst_fold_rank_ic = null
```

No synthetic financial observations are created to make such a run appear evaluable.

Candidate-level statistical invalidity (for example insufficient IC periods) is also a research result. It reduces `valid_candidate_count`; it is not silently repaired and is not automatically promoted to a system-level experiment failure when the evidence itself is complete.

## Freeze the preregistration artifact

PILOT:

```powershell
python scripts\freeze_us_a0_experiment_protocol.py `
  --phase pilot `
  --output reports\us_a0\us_a0_pilot_preregistration.json
```

FORMAL:

```powershell
python scripts\freeze_us_a0_experiment_protocol.py `
  --phase formal `
  --output reports\us_a0\us_a0_formal_preregistration.json
```

The bundles contain the exact vocabulary, experiment protocol and fixed MANUAL candidate grid. They have no project-status, stage-exit, Agent-value-gate or Alpha authority. Future execution must validate the complete bundle content, not merely accept a caller-supplied protocol ID string.

## Formal predecessor

When US-B0 is eventually complete, A0 must bind the exact content-addressed:

```text
finagent.us-baseline-walk-forward-evidence-graph.v1
```

The graph must be blocker-free, pass, report all eight US-B0 candidates valid and have `ready_for_us_a0_candidate=true`. A0 re-hashes the graph document before accepting the predecessor identity. Formal A0 also requires `docs/status.toml` to record the reviewed B0 graph/aggregate IDs and to have actually advanced to `current_stage=US-A0`.

## What remains after this increment

The evaluation contracts and synthetic bridge are implemented. The next execution-oriented A0 work after real US-B0 acceptance is:

1. add a formal fold materialization runner that consumes a validated preregistration bundle, accepted US-B0 predecessor/status authority and one content-addressed generation run;
2. write per-run fold materialization/evaluation manifests without duplicating US-B0 statistical formulas;
3. assemble authoritative `USAgentValueRunEvaluationReport` and `RunEvaluationLink` artifacts from the three frozen folds;
4. execute PILOT MANUAL / PROGRAMMATIC / AGENT runs under the same accepted data and evidence path;
5. calculate structural novelty/redundancy and generation-efficiency summaries;
6. review PILOT before any FORMAL result inspection and conduct a separate Agent Value Gate review without conflating it with the later deployment Alpha Gate.
