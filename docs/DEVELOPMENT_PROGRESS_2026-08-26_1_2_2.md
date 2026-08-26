# FinAgent 1.2.2 Development Progress Report

Date: 2026-08-26

This report tracks post-1.2.1 research-governance work against executable code invariants rather than README/roadmap statements alone.

## Status summary

| Workstream | Code status | Verification status | Merge status |
| --- | --- | --- | --- |
| ResearchProgram lifecycle | implemented | CI passed | merged to `main` via PR #20 |
| Agent-facing memory / OOS visibility | implemented | CI passed | merged to `main` via PR #21 |
| immutable ResearchRegistry identities | implemented on branch | PR #22 CI running | pending |
| formal Agent ExperimentFamily denominator | implemented on branch | PR #22 CI running | pending |
| governed Agent-market research entrypoint | implemented on branch | PR #22 CI running | pending |
| promotion-grade DSR/PBO/Reality Check binding | not yet connected to Agent-market final promotion | pending | pending |
| FinalStrategySpec | not implemented | pending | pending |
| atomic scoped evidence writer | not implemented | pending | pending |
| one-time sealed holdout evaluator | not implemented | pending | pending |
| deterministic ResearchPromotionGate | not implemented | pending | pending |

## 1. Delivered to `main`

### 1. ResearchProgram lifecycle

Executable state machine:

```text
OPEN
  ↓ freeze_program()
FROZEN
  ↓ close_program()
CLOSED
```

Code invariants:

- new research reservations require `OPEN`;
- exact previously reserved plans remain replayable after freeze;
- changed/new families are rejected after freeze;
- sealed holdout access requires `FROZEN`;
- sealed holdout consumption remains one-time;
- configured holdout must be consumed before close.

This closes the earlier gap where `ResearchProgramStatus` existed in the domain contract but the persistent store could not execute the intended lifecycle.

### 2. Research memory visibility

Agent-facing memory now uses a program-scoped read facade instead of direct raw-store traversal.

Evidence classes:

```text
SHARED
DEVELOPMENT
VALIDATION
SEALED_HOLDOUT
OPERATIONAL
```

Code invariants:

- raw memory remains complete for audit/replay;
- `SEALED_HOLDOUT` and `OPERATIONAL` evidence are never adaptive Agent inputs;
- development/validation evidence is restricted to its owning ResearchProgram;
- hidden results/failures cannot affect Agent budget recommendations;
- visibility classification is immutable;
- legacy unbound memory remains backward compatible.

## 2. PR #22 — current implementation

### Code-level defects found during review

The following issues were discovered by reading the concrete registry and Agent-market implementations rather than comparing documentation only.

#### Experiment identity could be rewritten

`ExperimentSpec` is defined as an immutable experiment definition, but the prior `SQLiteResearchRegistry.register_experiment()` used an upsert that could replace the fingerprint and payload under the same `experiment_id`.

That allowed a nominally pre-registered experiment to change dataset, code, universe or parameters after registration.

#### Result identity could be rewritten

The prior `register_result()` used replace semantics. A run result could therefore be overwritten after initial registration.

#### Agent candidate family was not a formal ExperimentFamily

The 1.2.1 Agent-market runner reserved ResearchProgram budget through a plan adapter, but the generated candidate tuple was not registered into `SQLiteResearchRegistry` as:

```text
ExperimentFamily
    ├─ ExperimentSpec candidate 1
    ├─ ExperimentSpec candidate 2
    └─ ...
```

Therefore the existing Phase 2.5 family-level validator could not prove that its DSR/PBO/Reality Check denominator was the same denominator used by Agent-market search.

## 3. PR #22 implementation

### Immutable registry identities

The registry now enforces:

```text
same ExperimentSpec -> idempotent
same experiment_id + changed spec -> reject
same run_id + different ExperimentSpec fingerprint -> reject
same ExperimentResult -> idempotent
same run_id + changed result -> reject
```

Artifact registration is also idempotent for the exact registered identity and rejects conflicting type/URI metadata.

### Formal Agent ExperimentFamily bridge

`AgentMarketExperimentFamilyBridge` now performs the pre-evaluation sequence:

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
```

Each generated feature is bound to:

- immutable generated-feature digest;
- immutable code artifact digest;
- primary dataset artifact;
- universe;
- task ID;
- ResearchProgram ID;
- ExperimentFamily ID.

A frozen family cannot be expanded or silently replaced by another candidate set.

### Cross-provider validation semantics

Provider validation does not rewrite the primary experiment dataset.

Example:

```text
Primary research: Alpaca dataset
        ↓
formal ExperimentSpec.dataset = Alpaca artifact
        ↓
secondary AKShare validation
        ↓
verify existing frozen family only
        ↓
ExperimentSpec.dataset remains Alpaca artifact
```

External-provider evidence is therefore validation evidence, not a mutation of the original research identity.

### Governed Agent-market entrypoint

A new `GovernedAgentMarketResearchRunner` composes the existing deterministic numerical runner.

Required ordering:

```text
preflight
  ↓
ResearchProgram reservation
  ↓
formal ExperimentFamily registration
  ↓
ExperimentFamily FROZEN
  ↓
AgentMarketResearchRunner numerical evaluation
```

The wrapper checks after evaluation that program ID, family ID and candidate digest set have not drifted from the frozen registration.

The existing low-level `AgentMarketResearchRunner` remains the deterministic numerical engine; promotion-oriented workflows should use the governed wrapper.

## 4. Regression targets in PR #22

Tests currently cover:

```text
ExperimentSpec rewrite rejection
ExperimentResult rewrite rejection
run_id rebinding rejection
exact registration idempotency
ResearchProgram budget reservation
formal family freeze
candidate membership denominator
frozen-family expansion rejection
cross-provider dataset identity preservation
replay requires existing formal family
candidate identity mismatch rejection
governed runner freezes family before numerical engine
invalid preflight does not consume program budget
```

CI remains the acceptance gate before merge.

## 5. Remaining 1.2.2 development sequence

The next work is intentionally ordered so sealed holdout cannot become a hidden tuning channel.

### Step A — bind promotion-grade statistics to formal Agent family

Connect the frozen Agent ExperimentFamily to the existing Phase 2.5 statistical controls:

```text
Holm / declared multiplicity correction
Deflated Sharpe Ratio
CSCV Probability of Backtest Overfitting
White-style Reality Check
```

The denominator must come from formal family membership, not from a caller-provided arbitrary matrix.

### Step B — FinalStrategySpec

Agent-market currently selects a feature independently inside each outer fold. That does not define one unique final strategy for a sealed holdout.

Before holdout access, introduce an immutable final strategy contract derived only from development/validation evidence.

The final contract must freeze at least:

```text
selected feature/model identity
training/calibration protocol
portfolio/risk configuration
cost model
universe contract
provider/data identity
execution clock
```

### Step C — atomic scoped evidence writer

Memory visibility currently treats legacy/unbound records as shared for compatibility. Therefore sensitive evidence cannot be written through `register_result()` first and classified afterward.

The holdout writer must commit:

```text
RESULT/FAILURE evidence
+
SEALED_HOLDOUT visibility scope
```

atomically in one SQLite transaction.

### Step D — one-time sealed holdout evaluator

Required preconditions:

```text
ResearchProgram == FROZEN
formal ExperimentFamily == FROZEN/CLOSED
FinalStrategySpec exists and is immutable
pre-holdout promotion gate passed
sealed holdout has not been consumed
```

Only then may the evaluator consume the holdout exactly once.

### Step E — deterministic ResearchPromotionGate

The final decision must be deterministic policy code, not an LLM judgment.

Expected inputs include:

```text
formal family validation report
final strategy identity
sealed holdout report
cost/turnover/risk checks
provider validation evidence
research lifecycle state
```

The gate should return an explicit pass/fail decision with reasons and no authority to mutate live financial state.

## 6. Current architecture after this increment

```text
PIT data / provider evidence
        ↓
Generated factor candidates
        ↓
ResearchProgram budget
        ↓
Formal ExperimentFamily
        ↓
Governed nested research
        ↓
Family-level promotion statistics        <- next
        ↓
FinalStrategySpec                        <- next
        ↓
ResearchProgram FROZEN
        ↓
One-time sealed holdout                  <- next
        ↓
SEALED_HOLDOUT scoped evidence           <- next
        ↓
Deterministic ResearchPromotionGate      <- next
        ↓
Model registry / paper-shadow workflow
```

## 7. Completion criterion for 1.2.2 research governance

1.2.2 should not be marked complete merely because all listed classes exist. Completion requires an executable end-to-end test proving:

```text
candidate generation
→ formal family freeze
→ development-only research
→ family statistical validation
→ final strategy freeze
→ program freeze
→ one-time sealed holdout
→ sealed evidence remains invisible to adaptive Agent reads
→ deterministic final promotion decision
```

Any missing transition means the governance chain remains incomplete.
