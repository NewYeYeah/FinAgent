# US-A0 controlled Agent incremental-value experiment

US-A0 answers a narrower question than the later Alpha Gate:

```text
Does the Agent add measurable research value versus fixed MANUAL and bounded PROGRAMMATIC search
under the same data, vocabulary, trial budget and split-bound evaluation evidence?
```

It does **not** ask whether any candidate is deployable. Agent Value Gate and Alpha Gate remain separate.

## Current authority boundary

The repository may preregister US-A0 contracts while the project-stage authority still reports US-D3 and while US-B0 real-data evidence is pending. Formal Agent-value financial execution is not authorized until:

```text
US-I0 active-session acceptance completed
MT5-D0 reconciliation accepted
US-D3 accepted
US-B0 real folds executed
US-B0 split-bound evidence graph accepted and recorded in docs/status.toml
project stage advanced through US-B0 to current_stage=US-A0
```

The continuous-market FX smoke is engineering evidence only and cannot be supplied as an A0 predecessor.

## Frozen preregistration identities

The PILOT and FORMAL bundles were frozen before any real A0 result inspection. Their deterministic identities are golden regression expectations:

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

Input fields are derived from primitive kind, not chosen by the generator. The structural space contains exactly 62 candidate formulas. Candidate identity is based on structural formula and vocabulary identity; wording does not create novelty.

## MANUAL arm and shared trial budget

The MANUAL arm is frozen before A0 results exist:

- first 8 formulas structurally reproduce the US-B0 MANUAL denominator;
- PILOT uses a fixed 16-formula grid;
- FORMAL uses a fixed 32-formula grid;
- additional formulas are a preregistered coverage grid, not performance-selected extensions.

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

An invalid or duplicate initial proposal consumes its slot. At most one repair is allowed inside the consumed slot. Replacement slots are forbidden. This prevents retry count from silently expanding the Agent search budget.

## Agent metadata and reasoning boundary

Every AGENT run binds:

```text
provider_id
model_id
prompt_template_id
generator_id
run_ordinal
```

Every Agent proposal/repair records:

```text
llm_calls
input_tokens
output_tokens
latency_ms
cost_usd
generated_at
```

Stored proposal content is limited to structured formula fields and a short hypothesis summary. Hidden chain-of-thought is neither required nor stored. Optional `parent_candidate_id` may reference a candidate already accepted earlier in the same run.

## Evidence contracts

The A0 evidence path now includes:

```text
USAgentValuePrimitiveVocabulary
USAgentValueCandidateSpec
USAgentValueExperimentProtocol
USAgentValueExecutionPlan
CandidateGenerationRunSpec
CandidateGenerationEvent
CandidateGenerationRun
USAgentValueEvaluationDenominator
USAgentValueEvaluationBinding
USAgentValueFoldExecutionSpec
USAgentValueFoldEvaluationReport
USAgentValueFoldMaterializationManifest
USAgentValueRunEvaluationReport
RunEvaluationLink
USAgentValueRunEvidenceManifest
ParsedUSAgentValueRunEvidence
SearchArmResult
AgentValueExperiment
AgentValueComparisonSnapshot
AgentValueExperimentEvidenceGraph
```

`RunEvaluationLink` links authoritative split-bound metrics rather than recomputing row-level statistics. `SearchArmResult` may derive generation-efficiency metrics and structural novelty from candidate IDs. `AgentValueExperiment` does not automatically declare a winner:

```text
agent_value_gate_decision = UNDECIDED_REQUIRES_SEPARATE_REVIEW
agent_value_gate_authority = false
alpha_authority = false
```

## Shared evaluation bridge

Every completed generation run is compiled into an A0-owned evaluation denominator containing only final `VALID_UNIQUE` structural candidates. Invalid and duplicate slots remain visible in generation evidence and still consume trial budget; they are never replaced merely to obtain a full financial denominator.

The evaluation binding copies accepted US-B0 authority and statistical gates:

```text
same US-D3 certification report
same certification outcome
same EngineeringUniverse
same 15m signal clock
same same-session 60m RAW label
same minimum cross-section / evaluated-period / IC-period gates
```

Only denominator identity changes. Feature formation and label admission reuse the US-B0 materializer implementation, and candidate statistics reuse `evaluate_us_baseline_candidate()`. A0 emits distinct A0 schemas rather than falsely serializing Agent results as pre-Agent MANUAL baseline evidence.

The experiment phase is explicit and content-addressed. A FORMAL 32-slot run remains FORMAL even if generation leaves only one accepted candidate.

A run with zero accepted candidates is a valid experiment result:

```text
status = NO_ACCEPTED_CANDIDATES
evaluated_candidate_count = 0
valid_candidate_count = 0
best_mean_rank_ic = null
best_worst_fold_rank_ic = null
```

No synthetic financial observations are created. Candidate-level statistical invalidity is likewise a research result, not a technical-system blocker when the data/evidence path itself is complete.

## Freeze the experiment preregistration

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

The bundle freezes vocabulary, protocol and MANUAL grid. It does **not** choose the concrete random seeds or Agent model identity for a particular experiment execution.

## Freeze the independent-run execution plan

The second preregistration layer is `USAgentValueExecutionPlan`. It prevents seed/model/run cherry-picking by freezing every independent `CandidateGenerationRunSpec` before candidate generation or financial evaluation.

If `--programmatic-seed` is omitted, the pre-result defaults are:

```text
PILOT   1729
FORMAL  1729, 2718, 3141
```

PILOT example:

```powershell
python scripts\freeze_us_a0_execution_plan.py `
  --preregistration reports\us_a0\us_a0_pilot_preregistration.json `
  --agent-provider <PROVIDER_ID> `
  --agent-model <MODEL_ID> `
  --agent-prompt-template <PROMPT_TEMPLATE_ID> `
  --output reports\us_a0\us_a0_pilot_execution_plan.json
```

FORMAL uses the FORMAL preregistration bundle and defaults to three PROGRAMMATIC seeds plus three AGENT independent run ordinals. PROGRAMMATIC and AGENT run counts must be equal and satisfy the frozen minimum; MANUAL remains exactly one canonical run.

Changing a seed, provider, model, prompt identity or run count creates a new execution-plan ID. An evaluator may only accept a generation-run spec explicitly authorized by that exact plan.

## Materialize deterministic control generation runs

MANUAL and PROGRAMMATIC candidate-generation evidence can be produced without financial data or an LLM:

```powershell
python scripts\prepare_us_a0_control_run.py `
  --preregistration reports\us_a0\us_a0_pilot_preregistration.json `
  --execution-plan reports\us_a0\us_a0_pilot_execution_plan.json `
  --arm manual `
  --run-ordinal 1 `
  --output reports\us_a0\generation\pilot_manual_01.json

python scripts\prepare_us_a0_control_run.py `
  --preregistration reports\us_a0\us_a0_pilot_preregistration.json `
  --execution-plan reports\us_a0\us_a0_pilot_execution_plan.json `
  --arm programmatic `
  --run-ordinal 1 `
  --output reports\us_a0\generation\pilot_programmatic_01.json
```

The PROGRAMMATIC candidate set is deterministic for the preauthorized seed. The generated-at timestamp is metadata and is retained in the content-addressed run evidence.

## Provider-neutral structured AGENT seam

`StructuredAgentSlotProvider` is the only provider-facing surface introduced at this stage. A concrete model integration may return only the already-frozen `ProposalSlot` structure. It cannot inject arbitrary feature code or change the experiment contract.

Before generation, `build_authorized_agent_generation_run()` requires the selected run spec to exist in the frozen `USAgentValueExecutionPlan` and checks exact equality of:

```text
provider_id
model_id
prompt_template_id
```

The provider then supplies structured slots, and the existing `build_candidate_generation_run()` remains authoritative for slot count, candidate vocabulary, duplicate handling, repair limit, replacement prohibition and usage metadata. A provider adapter therefore cannot bypass the shared trial budget merely because it uses a different external API.

No concrete provider API is bound in this layer. OpenAI, DeepSeek or a local model can be added later without changing the frozen A0 experiment schemas, provided the adapter implements this seam and the execution plan has preregistered its exact identities.

## Formal predecessor and financial runner

A0 must bind the exact `finagent.us-baseline-walk-forward-evidence-graph.v1`. The graph must be blocker-free, pass, retain all eight valid US-B0 candidates, and match the B0 graph/aggregate IDs recorded in `docs/status.toml` after review. Formal financial execution additionally requires `current_stage=US-A0` and accepted US-B0 stage-exit authority.

Only after those conditions are true may one preregistered generation run be evaluated:

```powershell
python scripts\materialize_us_a0_run.py `
  "D:\Data\datasets--mito0o852--OHLCV-1m" `
  --preregistration reports\us_a0\us_a0_pilot_preregistration.json `
  --execution-plan reports\us_a0\us_a0_pilot_execution_plan.json `
  --generation-run reports\us_a0\generation\pilot_manual_01.json `
  --us-b0-evidence-graph reports\us_b0\us_b0_walkforward_evidence_graph.json
```

The runner performs authority checks before any DuckDB query. For a nonempty generation run it executes exactly the three canonical US-B0 evaluation folds and writes, under `reports/us_a0/runs/<generation_run_id>/`:

```text
us_a0_evaluation_binding.json
fold_01/
  us_a0_input_plan.json
  us_a0_input_materialization.json
  us_a0_observation_artifact.json
  us_a0_diagnostics.json
  us_a0_fold_evaluation.json
  us_a0_fold_materialization_manifest.json
fold_02/...
fold_03/...
us_a0_run_evaluation.json
us_a0_run_evaluation_link.json
us_a0_run_evidence_manifest.json
```

Row-level Parquet/observation artifacts remain under `data/us_a0/runs/<generation_run_id>/`. Each fold retains the 100,000-row bounded Python guard.

Technical materialization blockers such as missing EngineeringUniverse assets, label-anchor loss or close-anchor drift terminate fail-closed with exit code 2. Weak/negative RankIC or candidate statistical insufficiency remains candidate evidence and does not turn a technically complete experiment into a system failure.

A zero-accepted-candidate generation run does not query market data; it writes a complete `NO_ACCEPTED_CANDIDATES` run evaluation/link/manifest and exits successfully as a valid negative search result.

## Assemble the exact three-arm experiment

After every generation run authorized by the frozen execution plan has a complete run-evidence directory, the experiment can be assembled without re-reading market rows:

```powershell
python scripts\assemble_us_a0_experiment.py `
  --preregistration reports\us_a0\us_a0_pilot_preregistration.json `
  --execution-plan reports\us_a0\us_a0_pilot_execution_plan.json `
  --generation-run reports\us_a0\generation\pilot_manual_01.json `
  --generation-run reports\us_a0\generation\pilot_programmatic_01.json `
  --generation-run reports\us_a0\generation\pilot_agent_01.json `
  --us-b0-evidence-graph reports\us_b0\us_b0_walkforward_evidence_graph.json
```

FORMAL requires all seven frozen runs rather than merely a subset satisfying minimum run counts. The assembler rejects missing, extra, duplicate, re-ordered-within-arm or cross-predecessor evidence.

For every run it re-hashes and cross-checks generation-run, run-evaluation, evaluation-link, run-manifest and nested fold-manifest evidence. Content hashes are treated as identities rather than signatures: the parser also derives candidate IDs and compiled feature IDs from generation evidence, recomputes valid-candidate count from candidate aggregates, and recomputes the best RankIC summaries from valid aggregate details. Re-hashing a semantically forged summary therefore does not make it authoritative.

The assembler writes:

```text
reports/us_a0/experiment/
  us_a0_manual_search_arm_result.json
  us_a0_programmatic_search_arm_result.json
  us_a0_agent_search_arm_result.json
  us_a0_agent_value_experiment.json
  us_a0_agent_value_comparison.json
  us_a0_agent_value_evidence_graph.json
```

`AgentValueExperimentEvidenceGraph` links the exact execution plan, preregistration bundle, reviewed predecessor, every generation-run ID, every run-evidence manifest, every authoritative run-evaluation report/link, all three arm results, the structural comparison and the final experiment ID.

Even when the graph reports:

```text
evidence_complete = true
ready_for_agent_value_gate_review = true
```

it still reports:

```text
agent_value_gate_decision = UNDECIDED_REQUIRES_SEPARATE_REVIEW
agent_value_gate_authority = false
alpha_authority = false
```

Experiment assembly is therefore an evidence-completeness transition, not an automatic claim that the Agent adds value.

## Current remaining A0 work

After this increment the controlled path from preregistration through exact three-arm experiment evidence is implemented, but real execution remains blocked by project-stage authority. Remaining work is:

1. add a concrete external-model adapter only after provider/model/prompt identities are intentionally selected and frozen in an execution plan;
2. complete Issue #125 → MT5-D0 → US-D3 → real US-B0 folds and record accepted B0 evidence in status;
3. advance to US-A0 and execute PILOT MANUAL / PROGRAMMATIC / AGENT runs under the exact execution plan;
4. assemble the PILOT experiment evidence graph and review it before any FORMAL result inspection;
5. freeze and conduct a separate Agent Value Gate review contract without changing the already-observed PILOT evidence;
6. keep Agent Value Gate distinct from the later deployment Alpha Gate.
