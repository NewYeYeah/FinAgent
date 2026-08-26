# FinAgent 1.2.2 Development Progress Report

Date: 2026-08-26

This report tracks post-1.2.1 research-governance work against executable code invariants rather than README/roadmap statements alone. A workstream is marked complete only after its production/governed path, regression tests and CI agree with the documented contract.

## Status summary

| Workstream | Code status | Verification status | Merge status |
| --- | --- | --- | --- |
| ResearchProgram lifecycle | implemented | CI passed | `main`, PR #20 |
| Agent-facing memory / OOS visibility | implemented | CI passed | `main`, PR #21 |
| immutable ResearchRegistry identities | implemented | CI passed | `main`, PR #22 |
| formal Agent ExperimentFamily denominator | implemented | CI passed | `main`, PR #22 |
| governed Agent-market CLI/entrypoint | implemented | CI passed | `main`, PR #22 |
| formal-family DSR/PBO/Reality Check binding | implemented on branch | PR #23 CI | pending |
| FinalStrategySpec | not implemented | pending | pending |
| atomic scoped evidence writer | not implemented | pending | pending |
| one-time sealed holdout evaluator | not implemented | pending | pending |
| deterministic ResearchPromotionGate | not implemented | pending | pending |

## 1. Delivered to `main`

### 1.1 ResearchProgram lifecycle — PR #20

Executable state machine:

```text
OPEN
  ↓ freeze_program()
FROZEN
  ↓ close_program()
CLOSED
```

Enforced invariants:

- new family reservations require `OPEN`;
- exact previously reserved plans remain replayable after freeze;
- changed/new families are rejected after freeze;
- sealed holdout access requires `FROZEN`;
- sealed holdout consumption is one-time;
- a configured holdout must be consumed before close.

### 1.2 Agent-facing evidence visibility — PR #21

Evidence classes:

```text
SHARED
DEVELOPMENT
VALIDATION
SEALED_HOLDOUT
OPERATIONAL
```

Enforced invariants:

- raw memory remains complete for deterministic audit/replay;
- `SEALED_HOLDOUT` and `OPERATIONAL` evidence are never adaptive Agent inputs;
- development/validation evidence is restricted to its owning ResearchProgram;
- hidden results/failures do not influence Agent lineage/failure/budget reads;
- visibility classification is immutable;
- legacy unbound memory remains readable for backward compatibility.

### 1.3 Immutable registry + formal Agent family — PR #22

Code review found that the pre-1.2.2 registry contradicted its domain semantics: `ExperimentSpec` was documented as immutable, but `register_experiment()` could overwrite an existing ID; `register_result()` could replace an existing result. The Agent-market candidate tuple also consumed a ResearchProgram budget without becoming a formal `ExperimentFamily`.

PR #22 changed the executable behavior to:

```text
same ExperimentSpec -> idempotent
same experiment_id + changed spec -> reject
same run_id + different ExperimentSpec fingerprint -> reject
same ExperimentResult -> idempotent
same run_id + changed result -> reject
```

Agent candidate governance now follows:

```text
GeneratedFeatureArtifact × N
        ↓
ResearchProgram reservation
        ↓
ExperimentFamily OPEN
        ↓
ExperimentSpec × N
        ↓
FamilyMembership × N
        ↓
ExperimentFamily FROZEN
        ↓
numerical evaluation
```

Each formal candidate binds the generated-feature/code digest, primary dataset artifact, universe, candidate parameters, task ID, ResearchProgram ID and ExperimentFamily ID.

`GovernedAgentMarketResearchRunner` makes this ordering explicit. The existing deterministic `AgentMarketResearchRunner` remains a low-level numerical engine, while `scripts/run_agent_market_research.py` now uses the governed runner by default.

The CLI also binds the normalized market-data manifest hash as the formal dataset digest:

```text
manifest.normalized_sha256
        ↓
ArtifactRef(DATASET)
        ↓
ExperimentSpec.dataset
```

Cross-provider validation verifies the existing frozen family and does not rewrite the primary ExperimentSpec dataset.

## 2. PR #23 — formal-family promotion statistics

### 2.1 Why another adapter is required

The existing Phase 2.5 statistical functions already implement:

```text
declared multiple-testing correction
Deflated Sharpe Ratio
CSCV Probability of Backtest Overfitting
White-style Reality Check
```

The remaining gap is not the mathematics. It is the input identity and information boundary.

The 1.2.1 Agent-market result intentionally exposes only the selected candidate's outer-fold evidence. That is correct for adaptive Agent feedback, but family-level anti-overfitting statistics need the development outer-return series of every pre-registered candidate.

PR #23 therefore creates a separate deterministic validation path instead of widening Agent-visible output.

### 2.2 `AgentFamilyDevelopmentEvidence`

This contract stores aligned development-only evidence for exactly one formal ExperimentFamily:

```text
family_id
formal experiment_order
common timestamps
trial_returns[experiment_id]
pvalues[experiment_id]
primary dataset digest
```

It rejects:

- missing or additional family members;
- non-finite/misaligned return series;
- duplicate timestamps;
- invalid p-values.

Duplicate timestamps are treated as a hard error rather than silently de-duplicated. This prevents overlapping outer folds from double-counting the same OOS time point in DSR/PBO inputs.

### 2.3 `AgentFamilyDevelopmentEvidenceBuilder`

The builder performs deterministic re-evaluation of every frozen formal member using the same nested splitter and generated-feature evaluator as Agent-market research.

Before evaluation it verifies:

```text
ExperimentFamily == FROZEN
candidate digests == formal member digests
code digest == formal ExperimentSpec.code
primary dataset == formal ExperimentSpec.dataset
universe == formal ExperimentSpec.universe
```

For each candidate it concatenates outer-test net returns, requires identical timestamp sequences across the entire family, and derives a one-sided mean-return p-value.

The resulting non-selected outer evidence is validation evidence only. It is not added to the adaptive Agent result or memory view.

### 2.4 `FormalAgentExperimentFamilyValidator`

The validator takes the formal family membership as the only admissible denominator.

Common family calculations:

```text
multiple-testing correction across all formal members
PBO on full (time × strategy) matrix
White Reality Check on full family matrix
```

Per-member calculation:

```text
DSR(candidate_i, n_trials = formal family size)
```

Candidate eligibility requires:

```text
adjusted p-value passes
AND DSR probability >= predeclared threshold
AND family PBO <= threshold
AND family Reality Check p-value <= family alpha
```

The report deliberately has **no `selected_experiment_id`**. At this stage the system is allowed to state which candidates are statistically eligible, but not to choose the final sealed-holdout strategy.

### 2.5 Durable statistical report

`SQLiteAgentFamilyValidationStore` stores the deterministic report append-only using a hash-derived report identity. Exact re-registration is idempotent; changed content produces a different identity rather than overwriting prior evidence.

### 2.6 PR #23 regression targets

```text
formal family must be FROZEN
validation denominator must match formal membership/order
DSR n_trials == formal family size
PBO/Reality Check use full formal matrix
overlapping outer timestamps rejected
strong candidate can be eligible under explicit test thresholds
weak/non-significant candidate remains in denominator but is not eligible
report contains no final selected_experiment_id
validation report persistence is append-only/idempotent
```

CI remains the acceptance gate before merge.

## 3. Development sequence after PR #23

### Step B — FinalStrategySpec

Agent-market currently may select a different feature in each outer fold. Sealed holdout evaluation requires one immutable strategy selected **before** holdout access.

The next contract must freeze at minimum:

```text
selected formal experiment/feature identity
family statistical report identity
training/calibration protocol
risk model configuration
portfolio construction configuration
cost model
universe contract
primary provider/data identity
execution clock/lag
selection rule/version
```

The selector must consume development/validation evidence only. No sealed-holdout metric may participate in selection.

### Step C — atomic scoped evidence writer

Legacy/unbound memory is readable for compatibility. Therefore sensitive holdout evidence cannot safely be written by calling raw `register_result()` and binding its `SEALED_HOLDOUT` scope in a second transaction.

Required transaction:

```text
RESULT / FAILURE node + lineage
AND
SEALED_HOLDOUT visibility scope
```

must commit atomically or not at all.

### Step D — one-time sealed holdout evaluator

Required preconditions:

```text
formal ExperimentFamily == FROZEN/CLOSED
FinalStrategySpec exists and is immutable
pre-holdout statistical gate passed
ResearchProgram == FROZEN
sealed holdout has not been consumed
```

Only then may the holdout be consumed exactly once.

### Step E — deterministic ResearchPromotionGate

Final promotion remains deterministic policy code, not an LLM decision. Expected inputs:

```text
formal family statistical report
FinalStrategySpec
sealed holdout report
cost/turnover/risk checks
provider validation evidence
ResearchProgram lifecycle state
```

The gate returns explicit pass/fail reasons and has no authority to bypass model registry or paper/shadow controls.

## 4. Current architecture

```text
PIT market data + immutable manifest
        ↓
LLM/generated candidates
        ↓
ResearchProgram budget
        ↓
Formal ExperimentFamily FROZEN
        ↓
Governed nested research
        ↓
Development evidence for all formal members
        ↓
Multiplicity + DSR + PBO + Reality Check       PR #23
        ↓
Eligible candidate set
        ↓
FinalStrategySpec                              NEXT
        ↓
ResearchProgram FROZEN
        ↓
One-time sealed holdout                        NEXT
        ↓
Atomic SEALED_HOLDOUT evidence                 NEXT
        ↓
Deterministic ResearchPromotionGate            NEXT
        ↓
Model registry / paper-shadow workflow
```

## 5. 1.2.2 completion criterion

1.2.2 must not be marked complete because all named classes exist. Completion requires an executable end-to-end test proving:

```text
candidate generation
→ formal family freeze
→ development-only nested research
→ full-family statistical validation
→ immutable final strategy freeze
→ ResearchProgram freeze
→ one-time sealed holdout
→ sealed evidence remains invisible to adaptive Agent reads
→ deterministic final promotion decision
```

Any missing or bypassable transition means the research-governance chain remains incomplete.
