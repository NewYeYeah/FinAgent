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

The first A0 increment introduces:

```text
USAgentValuePrimitiveVocabulary
USAgentValueCandidateSpec
USAgentValueExperimentProtocol
CandidateGenerationRunSpec
CandidateGenerationEvent
CandidateGenerationRun
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

## Freeze the preregistration artifact

This can be done before formal US-A0 execution because it does not consume research results.

PILOT:

```powershell
python scripts\freeze_us_a0_experiment_protocol.py `
  --phase pilot `
  --output reports\us_a0\us_a0_pilot_preregistration.json
```

FORMAL protocol can also be frozen independently:

```powershell
python scripts\freeze_us_a0_experiment_protocol.py `
  --phase formal `
  --output reports\us_a0\us_a0_formal_preregistration.json
```

The bundles contain the exact vocabulary, experiment protocol and fixed MANUAL candidate grid. They have no project-status, stage-exit, Agent-value-gate or Alpha authority.

## Formal predecessor

When US-B0 is eventually complete, A0 must bind the exact content-addressed:

```text
finagent.us-baseline-walk-forward-evidence-graph.v1
```

The graph must be blocker-free, pass, report all eight US-B0 candidates valid and have `ready_for_us_a0_candidate=true`. A0 re-hashes the graph document before accepting the predecessor identity. This binding does not itself advance `docs/status.toml`; stage authority remains separate.

## What remains after this increment

The next A0 work after real US-B0 acceptance is:

1. compile accepted structural candidates into arm-specific evaluation denominators;
2. run every arm through the same frozen folds and evaluation semantics;
3. build authoritative `RunEvaluationLink` values from those split-bound reports;
4. calculate structural novelty/redundancy and generation-efficiency summaries;
5. run PILOT and review whether the preregistered FORMAL experiment remains appropriate before any formal result inspection;
6. conduct a separate Agent Value Gate review without conflating it with the later deployment Alpha Gate.
