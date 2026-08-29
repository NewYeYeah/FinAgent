# A-share One-shot Reserve Governance

This guide covers the A5 reserve protocol. **A5-1 eligibility sealing and A5-2 deterministic one-shot runner/terminal evidence are implemented.** No production 2025+ reserve has been consumed. A5-2 remains intentionally non-runnable as a production workflow until A5-3 adds a crash-safe durable pre-access `CONSUMED` claim.

## Authority boundary

The reserve lifecycle remains:

```text
A2.6 frozen ResearchProgram
        ↓
A4 frozen execution-aware validation
        ↓
V2 human evidence review
        ↓
A5-1 ReserveEligibilitySeal      ✓
        ↓
A5-2 runner + terminal evidence  ✓ code/CI only
        ↓
A5-3 crash-safe CONSUMED state   ← production blocker
```

`ReserveEligibilitySeal` remains the immutable permission prerequisite. A5-2 accepts only that persisted seal, the exact sealed A2.6/A4 reports and the sealed Git identity. It adds no Agent/UI execution route and does not mutate eligibility state. Because A5-2 deliberately does not own the durable pre-access consumption claim, **the real reserve must not be run until A5-3 is complete**.

The frozen A5 authority policy rejects any configuration that enables:

- Agent feedback from reserve evidence;
- factor replacement or reserve-based weight refit;
- Gate/threshold mutation;
- risk/optimizer mutation;
- fee/slippage mutation;
- rebalance-cadence mutation;
- UI interactive tuning;
- Agent or UI reserve authority.

## Inputs required by A5-1

A5-1 binds the exact artifacts below:

```text
A2.6 reference report
A2.6 exact-replay report
A4 reference report
A4 exact-replay report
A4 immutable JSONL execution ledger
Visualization V2 human-review bundle
V2 human review attestation
clean Git commit identity for the future A5 runner
```

The sealer validates, among other things:

- A2.6 `program_status=frozen`;
- frozen robust factor family exists;
- A2.6/A4 reserve ID and interval agree and remain `untouched`;
- A4 execution/economic validation passed;
- A4 source report digest binds the exact A2.6 report;
- A4 factor digests, directions and weights exactly equal the A2.6 frozen selection;
- A4 execution ledger recomputes to the report's `ledger_digest`;
- A2.6 and A4 replay reports are exact modulo the non-authoritative `mode` field;
- the V2 review ZIP contains the same A2.6/A4/ledger artifacts;
- human review attestation binds the exact review ZIP and declares every V2 acceptance check PASS.

Any mismatch fails closed and no seal is persisted.

## Human V2 review attestation

After manually reviewing the exact V2 cockpit and bundle, create the attestation. Every required acceptance check must be stated explicitly.

```powershell
python scripts/attest_v2_reserve_review.py `
  --program-result-id <A2.6_PROGRAM_RESULT_ID> `
  --portfolio-validation-id <A4_VALIDATION_ID> `
  --review-bundle reports\finagent-review-<A4_VALIDATION_ID>.zip `
  --workspace-commit-sha <CI_VERIFIED_COMMIT> `
  --reviewed-by <REVIEWER_ID> `
  --passed-check python_api `
  --passed-check typescript `
  --passed-check vitest `
  --passed-check vite_build `
  --passed-check playwright `
  --passed-check quality `
  --passed-check windows `
  --passed-check ubuntu `
  --passed-check legacy_streamlit `
  --passed-check read_only_authority `
  --confirm-protocol-identity-reviewed `
  --confirm-execution-ledger-reviewed `
  --confirm-reserve-untouched `
  --confirm-no-post-a4-mutation `
  --confirm-no-agent-feedback-path `
  --output .finagent\a5\v2-review-attestation.json
```

This is an explicit human attestation, not an automated substitute for reviewing the evidence.

## Create the eligibility seal

Generate fresh A2.6/A4 exact replay artifacts first using the existing `--assert-replay --frozen-report` workflows. Then run:

```powershell
python scripts/seal_ashare_reserve_eligibility.py `
  --a26-report reports\local_ashare_robust_research_a26.json `
  --a26-replay reports\local_ashare_robust_research_a26_replay.json `
  --a4-report reports\local_ashare_portfolio_validation_a4.json `
  --a4-replay reports\local_ashare_portfolio_validation_a4_replay.json `
  --a4-ledger reports\local_ashare_portfolio_validation_a4_ledger.jsonl `
  --review-bundle reports\finagent-review-<A4_VALIDATION_ID>.zip `
  --review-attestation .finagent\a5\v2-review-attestation.json `
  --state-db .finagent\a5\reserve_eligibility.sqlite `
  --output reports\reserve_eligibility_a5.json
```

The command automatically obtains the Git `HEAD` identity and refuses a dirty working tree. The SQLite store is append-only and allows only one exact eligibility identity for a reserve/program/A4 tuple.

## Seal semantics

The seal records:

- exact A2.6/A4 report SHA-256 digests and evidence IDs;
- A2.6 program spec and frozen selection identities;
- selected factor digests, weights and directions;
- A4 spec and ledger identities;
- reserve ID/interval with `status=untouched`;
- complete frozen protocol snapshot and digest;
- exact replay proof;
- V2 review bundle and human-attestation identities;
- V2 reviewed commit and A5 code Git identity;
- fail-closed authority policy digest;
- `eligibility_status=ELIGIBLE_SEALED` and `reserve_consumed=false`.

`created_at` is audit metadata and is not part of `seal_id`, so replaying A5-1 over identical frozen inputs produces the same identity.

## What A5-1 deliberately does not do

A5-1 does not:

- load any bar inside the reserve interval;
- calculate reserve performance;
- emit `RESERVE_PASS` or `RESERVE_FAIL`;
- change reserve state to `CONSUMED`;
- close/promote a strategy;
- expose a Workspace write route.

A5-2 now owns deterministic evaluation and terminal evidence; A5-3 still owns durable consumed-state mutation and crash-safe replay/audit.
## A5-2 deterministic runner semantics

A5-2 reuses the audited A4 alpha/risk/optimizer/A3 execution mechanics, but assigns separate terminal reserve semantics. The execution identity is deterministic over the A5-1 seal, reserve identity and fixed execution-protocol ID.

Final training follows `all-pre-reserve-half-open-v1`:

```text
train = first A2.6 development start → reserve.start (exclusive)
test  = reserve.start → reserve.end (exclusive)
```

Canonical forward labels already become `NaN` at the end of a split when their target session is outside the split, so fitting through the half-open pre-reserve boundary does not import a forward label from the reserve. The reserve calendar is materialized once and the resulting ordered sessions are passed into the terminal A4 fold, avoiding a second calendar materialization.

The terminal policy is `reuse-frozen-a4-economic-policy-v1`: no threshold is re-estimated from reserve evidence. A completed run emits exactly one of:

```text
RESERVE_PASS
RESERVE_FAIL
```

An operational exception after the one-shot execution starts is conservatively recorded as terminal `RESERVE_FAIL` with `EXECUTION_FAILURE` and `AUTOMATIC_RETRY_FORBIDDEN`; it is never treated as permission to retry. PASS never promotes automatically: terminal evidence always records `promotion_eligible=false` and leaves promotion to A6.

A5-2 persists append-only terminal evidence and binds the reserve dataset digest, terminal execution-ledger digest/file SHA, fold evidence, aggregate evidence, frozen policy and failure reason codes. It is idempotent for an already persisted terminal result and will not re-enter the engine on re-inspection.

### Why production execution is still blocked

A5-2 cannot by itself close the crash window between the first reserve observation access and persistence of terminal evidence. The terminal payload therefore records:

```text
consumed_state_persistence = PENDING_A5_3
```

A5-3 must atomically claim the reserve as consumed **before** the first observation access, survive process failure, persist/recover the terminal ledger and reject every subsequent consumption attempt. Until that exists, A5-2 is a tested engine boundary, not authorization to run the real reserve.
