# US-A0 Agent Value Gate review

The Agent Value Gate answers a narrower question than the later Alpha Gate:

```text
Under the exact preregistered data, grammar, candidate budget, run count and evaluation path,
did the AGENT arm add practically meaningful research-search value versus both MANUAL and PROGRAMMATIC?
```

It does **not** decide whether a trading strategy has deployable Alpha. A positive Agent Value Gate can coexist with a later failed Alpha Gate; a negative Agent Value Gate can coexist with a later successful non-Agent Alpha Gate.

## Authority boundary

The Gate has four distinct layers:

```text
frozen Gate policy
      ↓
deterministic Gate assessment
      ↓
independent Gate review
      ↓
optional acceptance in docs/status.toml
```

The policy and assessment have no Agent Value Gate authority. A reviewer may accept the deterministic assessment or downgrade it to `INCONCLUSIVE`; the reviewer may never upgrade a negative or inconclusive assessment to a positive decision.

PILOT review is not the final Agent Value Gate. Its only positive authority is permission to continue to FORMAL after the exact review ID is separately accepted in `docs/status.toml`.

FORMAL review is the Agent Value Gate result. Even then:

```text
status_authority = false
stage_exit_authority = false
alpha_authority = false
```

Project-stage progression remains governed only by `docs/status.toml`.

## Frozen practical-value rule

The v1 Gate deliberately uses preregistered practical-effect rules rather than introducing a post-result p-value test over three search runs.

Primary quality metric:

```text
best_worst_fold_rank_ic
```

Secondary quality metric:

```text
best_mean_rank_ic
```

A positive assessment requires all of the following:

1. AGENT median primary quality exceeds both the MANUAL value and PROGRAMMATIC median by at least **0.01 RankIC**;
2. AGENT median secondary quality exceeds both baselines by at least **0.01 RankIC**;
3. the same 0.01 superiority holds at the preregistered run level for:
   - PILOT: **1 / 1** AGENT run;
   - FORMAL: at least **2 / 3** AGENT runs (or the corresponding two-thirds ceiling if a future preregistered plan contains more runs);
4. AGENT search efficiency is non-inferior to PROGRAMMATIC:
   - valid-candidate rate may be at most **10 percentage points lower**;
   - invalid+duplicate slot rate may be at most **10 percentage points higher**;
5. AGENT produces at least **1 structural candidate** absent from both MANUAL and PROGRAMMATIC.

The 0.01 RankIC threshold is a practical relative-effect requirement for the search experiment. It is not an Alpha threshold and is not evidence that any candidate is tradable.

## Negative and inconclusive rules

A clear negative assessment requires:

```text
no AGENT run is better than both MANUAL and its ordinal-matched PROGRAMMATIC run
on both quality metrics
AND
AGENT has no meaningful search-efficiency advantage
```

A meaningful efficiency advantage is defined as either:

```text
valid-candidate rate >= PROGRAMMATIC + 10 percentage points
OR
invalid+duplicate rate <= PROGRAMMATIC - 10 percentage points
```

Complete-evidence outcomes between the positive and clear-negative rules are `INCONCLUSIVE`. This prevents a small, unstable or one-dimensional improvement from being relabeled as Agent value after results are known.

## Phase-specific decisions

PILOT decisions:

```text
PILOT_PROCEED_TO_FORMAL
PILOT_DO_NOT_PROCEED_TO_FORMAL
INCONCLUSIVE
```

FORMAL decisions:

```text
FORMAL_INCREMENTAL_VALUE_SUPPORTED
FORMAL_NO_INCREMENTAL_VALUE
INCONCLUSIVE
```

A PILOT result never emits `FORMAL_INCREMENTAL_VALUE_SUPPORTED`.

## Cost treatment

Agent provider/model/token/cost/latency evidence remains mandatory generation evidence. In Gate policy v1, monetary cost is reported as a diagnostic rather than subjected to a universal USD ceiling because the real provider/model has not yet been frozen and local-model economics are not comparable to hosted-API pricing.

This does not make cost irrelevant. It prevents an arbitrary provider-independent dollar threshold from being invented before the actual execution plan exists. A later policy revision may add a provider-specific cost ceiling only under a new content identity and before consuming the corresponding results.

## Freeze the Gate policy before results

PILOT:

```powershell
python scripts\freeze_us_a0_agent_value_gate_policy.py `
  --preregistration reports\us_a0\us_a0_pilot_preregistration.json `
  --output reports\us_a0\us_a0_pilot_gate_policy.json
```

FORMAL:

```powershell
python scripts\freeze_us_a0_agent_value_gate_policy.py `
  --preregistration reports\us_a0\us_a0_formal_preregistration.json `
  --output reports\us_a0\us_a0_formal_gate_policy.json
```

The policy files are pre-result artifacts and may be frozen now while the project stage remains US-D3. They have no stage, Gate or Alpha authority.

## Review an assembled experiment

Real review is only valid when the project has reached `current_stage=US-A0`, the reviewed US-B0 predecessor is accepted, and all exact ExecutionPlan runs have complete evidence.

Example PILOT review:

```powershell
python scripts\review_us_a0_agent_value_gate.py `
  --preregistration reports\us_a0\us_a0_pilot_preregistration.json `
  --execution-plan reports\us_a0\us_a0_pilot_execution_plan.json `
  --gate-policy reports\us_a0\us_a0_pilot_gate_policy.json `
  --generation-run reports\us_a0\generation\pilot_manual_01.json `
  --generation-run reports\us_a0\generation\pilot_programmatic_01.json `
  --generation-run reports\us_a0\generation\pilot_agent_01.json `
  --reviewer-id <REVIEWER_ID> `
  --review-notes "Reviewed exact preregistered PILOT evidence." `
  --attest-thresholds-unchanged `
  --attest-evidence-lineage `
  --ack-alpha-gate-separate `
  --ack-stage-authority-separate
```

The script reassembles the experiment from the exact generation/run evidence before assessing it. It does not trust a copied summary table and does not recompute row-level financial statistics.

Outputs:

```text
reports/us_a0/gate/us_a0_pilot_gate_assessment.json
reports/us_a0/gate/us_a0_pilot_gate_review.json
```

For FORMAL review, `--pilot-gate-review` is additionally required.

## Status-bound PILOT → FORMAL authority

A `PILOT_PROCEED_TO_FORMAL` review does not become usable merely because its JSON hash exists. Before FORMAL review authority is recognized, `docs/status.toml` must separately record the reviewed artifact:

```toml
[stage.us_a0]
pilot_gate_review_status = "accepted"
pilot_gate_review_id = "us-agent-value-gate-review-..."
pilot_formal_progression_approved = true
```

The exact review ID is rechecked against the review document. A different review, a pending status, missing attestation, `INCONCLUSIVE`, or `PILOT_DO_NOT_PROCEED_TO_FORMAL` fails closed.

This status structure is a future US-A0 requirement; it must **not** be added to the current US-D3 status as if PILOT had already run.

## Reviewer restrictions

The independent reviewer must attest that:

```text
Gate thresholds were not changed after seeing results
evidence lineage was checked
Alpha Gate is separate
project-stage authority is separate
```

The reviewer may downgrade any deterministic recommendation to `INCONCLUSIVE` with substantive notes. The reviewer may not transform:

```text
PILOT_DO_NOT_PROCEED_TO_FORMAL -> PILOT_PROCEED_TO_FORMAL
FORMAL_NO_INCREMENTAL_VALUE    -> FORMAL_INCREMENTAL_VALUE_SUPPORTED
INCONCLUSIVE                   -> any positive decision
```

Changing the policy itself requires a new policy identity and must happen before the affected experiment results are consumed.

## Interpretation after FORMAL

`FORMAL_INCREMENTAL_VALUE_SUPPORTED` means only that the preregistered Agent search process added measurable research-search value under this bounded experiment. It supports retaining Agent scope into US-R1 research, not deploying a strategy.

`FORMAL_NO_INCREMENTAL_VALUE` supports contracting Agent scope while continuing US-R1 with deterministic/manual research if warranted.

`INCONCLUSIVE` supports neither a positive Agent-value claim nor a negative claim. It does not authorize post-hoc threshold relaxation.

In all cases, the later US-R1 Alpha Gate remains independent.
