# FinAgent 1.2.2 — Research Governance Hardening

FinAgent 1.2.2 hardens the post-1.2.1 research boundary from three directions: executable ResearchProgram lifecycle, Agent-facing evidence visibility, and a formal immutable ExperimentFamily denominator for generated Agent candidates.

The governing rule for this work is code-level rather than documentary: a milestone is not complete because a status enum, README section or validation function exists. The runtime path must enforce the intended transition before evidence can be observed.

## 1. ResearchProgram state machine

```text
OPEN
  │
  │ freeze_program()
  ▼
FROZEN
  │
  │ optional one-time sealed holdout access
  │
  │ close_program()
  ▼
CLOSED
```

Allowed transitions are only:

```text
OPEN   -> FROZEN
FROZEN -> CLOSED
```

There is no reopen transition. Lifecycle events are append-only.

### Core invariants

New research requires `OPEN`. A new `(program_id, family_id)` reservation is rejected once the program is frozen or closed.

Exact replay remains possible after freezing. An already-reserved plan with the same family ID and fingerprint remains idempotently reservable after freeze/close; a changed plan or a new family fails.

```text
FROZEN
  existing exact plan replay -> allowed
  new hypothesis/family      -> denied
  changed existing family    -> denied
```

Sealed holdout requires `FROZEN`. `consume_sealed_holdout()` fails while the program is `OPEN`.

Holdout access remains one-time. The `research_program_holdout_access` uniqueness contract prevents a second access.

Programs with a configured holdout cannot close before consuming it. Programs without a configured holdout may close directly after freezing.

## 2. Research memory visibility

The raw memory store remains a complete audit/lineage store. Adaptive Agent reads are now mediated by a program-scoped visibility facade.

Evidence classes:

```text
SHARED
DEVELOPMENT
VALIDATION
SEALED_HOLDOUT
OPERATIONAL
```

Agent visibility rules:

```text
SHARED                    -> readable
DEVELOPMENT/VALIDATION    -> only owning ResearchProgram
SEALED_HOLDOUT            -> never adaptive Agent input
OPERATIONAL               -> never adaptive research input
legacy unbound evidence   -> readable for backward compatibility
```

Hidden evidence is filtered from lineage, failures and budget recommendation counts. The raw store remains complete for deterministic audit, replay and final promotion code.

Visibility classification is immutable. Sensitive evidence that should later become general prior knowledge must be published as a separate `SHARED` artifact; an existing sealed result is not relabeled after its outcome is known.

## 3. Formal Agent ExperimentFamily denominator

Code review after 1.2.1 found that Agent-market candidates consumed a ResearchProgram budget but were not registered as a formal `ExperimentFamily` in `SQLiteResearchRegistry`. The runtime therefore had a frozen Python candidate tuple without a durable statistical family identity.

That was insufficient for Phase 2.5 controls such as DSR, PBO and White-style Reality Check because the validator could not prove that its denominator was the same denominator searched by the Agent.

The 1.2.2 family bridge now enforces:

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

Each candidate `ExperimentSpec` binds:

```text
generated feature digest
code artifact digest
primary dataset artifact
universe
parameters/lookback/input fields
ResearchProgram ID
ExperimentFamily ID
task identity
```

A frozen family cannot be expanded or replaced by a different candidate set.

## 4. Registry immutability

Another code-level review finding was that the previous registry used upsert/replace semantics where the domain contract claimed immutability.

1.2.2 therefore requires:

```text
same ExperimentSpec registration       -> idempotent
same experiment_id + changed payload    -> reject
same run_id + different spec fingerprint-> reject
same ExperimentResult registration      -> idempotent
same run_id + changed result             -> reject
```

The purpose is not general database strictness. These identities define the research denominator and evidence lineage used by later statistical decisions.

## 5. Cross-provider validation

External-provider validation must not mutate the original research identity.

Example:

```text
primary research: Alpaca
ExperimentSpec.dataset = Alpaca artifact
        ↓
secondary validation: AKShare
        ↓
verify existing frozen family
        ↓
ExperimentSpec.dataset remains Alpaca artifact
```

The secondary provider produces validation evidence; it does not rewrite the primary ExperimentSpec.

## 6. Governed Agent-market entrypoint

`GovernedAgentMarketResearchRunner` is the promotion-oriented entrypoint around the existing deterministic `AgentMarketResearchRunner` numerical engine.

Required ordering:

```text
preflight
  ↓
ResearchProgram reservation
  ↓
formal family registration
  ↓
ExperimentFamily FROZEN
  ↓
nested numerical research
  ↓
post-run program/family/candidate identity check
```

The preflight runs before budget consumption so unsupported universes or malformed candidate families do not consume ResearchProgram capacity.

The low-level numerical runner remains useful as a deterministic engine, but a workflow that can feed promotion governance should pass through the governed wrapper.

## 7. Persistence model

The immutable `research_programs.payload_json` row remains unchanged for backward compatibility. Lifecycle state is stored separately in `research_program_lifecycle_events`.

Research memory visibility is stored orthogonally to immutable memory-node payloads.

Formal experiment-family membership remains in `SQLiteResearchRegistry` and is frozen through the existing `ExperimentFamilyStatus` transition contract.

These stores have different responsibilities:

```text
ResearchProgramStore      -> cross-family search/alpha budget and lifecycle
ResearchRegistry          -> immutable experiment/family/model identities
ResearchMemoryStore       -> cross-registry evidence/lineage
MemoryVisibilityStore     -> adaptive Agent read policy
```

## 8. Verification targets

Implemented tests cover:

```text
OPEN holdout access fails
OPEN -> FROZEN works
new research after freeze fails
exact existing reservation replay after freeze succeeds
changed existing family fails
holdout can be consumed only once
FROZEN -> CLOSED works
closed programs reject new research

sealed memory hidden from Agent reads
program-scoped development/validation memory
hidden evidence excluded from failure/budget counts
visibility classification immutability

ExperimentSpec rewrite rejection
ExperimentResult rewrite rejection
run_id rebinding rejection
formal candidate family freeze
frozen family expansion rejection
cross-provider primary dataset preservation
replay requires existing formal family
governed runner freezes family before numerical engine
invalid preflight does not consume budget
```

CI remains the acceptance gate for each PR before merge.

## 9. Remaining 1.2.2 sequence

### A. Bind promotion-grade statistics to the formal Agent family

Use formal `FamilyMembership` as the denominator for:

```text
declared multiplicity correction
Deflated Sharpe Ratio
CSCV Probability of Backtest Overfitting
White-style Reality Check
```

The validator must not accept an arbitrary caller-supplied denominator that differs from the frozen family.

### B. Freeze a unique FinalStrategySpec

The current Agent-market nested procedure may select a different feature in different outer folds. A sealed holdout requires one frozen final strategy before the holdout is observed.

The final strategy identity must be derived only from development/validation evidence and freeze at least feature/model identity, calibration/training protocol, risk/portfolio configuration, cost model, universe, data/provider identity and execution clock.

### C. Add an atomic scoped evidence writer

Legacy/unbound memory is readable for compatibility. Therefore holdout evidence cannot safely be written through a raw result API and classified in a later transaction.

Sensitive result/failure persistence must atomically write:

```text
evidence row/node
+
SEALED_HOLDOUT visibility scope
```

### D. Add the one-time sealed holdout evaluator

Required preconditions:

```text
ResearchProgram == FROZEN
formal ExperimentFamily == FROZEN/CLOSED
FinalStrategySpec exists
pre-holdout promotion gate passed
holdout not previously consumed
```

### E. Add deterministic ResearchPromotionGate

The final promotion decision is policy code, not an LLM judgment. It should consume formal family validation, final strategy identity, sealed holdout report, risk/cost checks, provider validation evidence and lifecycle state, and return explicit pass/fail reasons without live-capital authority.

## 10. Completion criterion

1.2.2 research governance is complete only when an end-to-end test proves:

```text
candidate generation
→ formal family freeze
→ development-only research
→ family statistical validation
→ final strategy freeze
→ ResearchProgram freeze
→ one-time sealed holdout
→ sealed evidence invisible to adaptive Agent reads
→ deterministic final promotion decision
```

The existence of isolated classes/functions is not sufficient if any transition can still be bypassed in the governed path.
