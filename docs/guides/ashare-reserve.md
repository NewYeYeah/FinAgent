# A-share One-shot Reserve Governance

This guide covers the A5 reserve protocol. The current implementation milestone is **A5-1 ReserveEligibilitySeal**. A5-1 does **not** open, read, evaluate or consume the 2025+ reserve.

## Authority boundary

The reserve lifecycle remains:

```text
A2.6 frozen ResearchProgram
        ↓
A4 frozen execution-aware validation
        ↓
V2 human evidence review
        ↓
A5-1 ReserveEligibilitySeal      ← implemented
        ↓
A5-2 one-shot reserve runner     ← not implemented yet
        ↓
A5-3 terminal consumed state
```

`ReserveEligibilitySeal` is only a permission prerequisite for a later human-authorized one-shot runner. It has no API or method that can mark reserve data as consumed.

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

Those responsibilities belong to A5-2/A5-3 and require a separate bounded PR after a real production seal is reviewed.
