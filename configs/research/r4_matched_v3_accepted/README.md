# Accepted R4 provider admission and matched v3 freeze

This directory records previously completed offline evidence from 2026-09-07,
independently reviewed as `EVIDENCE_ACCEPTED` and recorded on 2026-09-08.
It closes the B-005 admission blocker. B-006 remains OPEN: the real matched
campaign has **not executed**, and R4 has no Agent-value result, accepted
AdaptiveStrategy or stage terminal. Alpha/PAPER/Live/R5 authority is unchanged.

## Evidence ownership

| File | Meaning |
| --- | --- |
| [probe_request.json](probe_request.json) | Byte-preserved public non-research probe contract; no research feedback or returned model message |
| [provider_admission.json](provider_admission.json) | Byte-preserved accepted provider identity and verified transport receipt |
| [accepted_freeze_attestation.json](accepted_freeze_attestation.json) | Sanitized reference to the full immutable local freeze, with protocol facts and authority flags |
| [evidence_review.json](evidence_review.json) | Accepted review disposition, verified identities/hashes and historical failure preservation |

The **full original `campaign_freeze.json` remains local immutable authority**.
Its embedded ResearchAdmission/input bindings contain absolute local filesystem
paths, so it is not redistributed here. It was neither edited nor regenerated
for publication. The attestation has its own schema and is not a replacement
freeze, cannot be passed to the execution operator, and grants no separate
execution authority. Local environment dumps, databases, market data, raw model
messages and the full review bundle are not published.

## Accepted identities

| Binding | Exact value |
| --- | --- |
| Frozen executable main | `edf7c1942b3acf97926390e45bd46c8ac9aacbee` |
| ResearchAdmission | `r4-research-admission-61df92c1caacb80e369f538f` |
| ProviderAdmission | `r4-provider-admission-b78a63f33352d5a01bf2a4ca` |
| Probe contract | `r4-provider-probe-contract-fe25be88367262b64ee310ec` |
| CampaignFreeze | `r4-campaign-freeze-1d12fade12cb269d2b4da416` |
| Protocol | `r4-matched-protocol-191d511a8addb59081d261e8` / `r4-matched-v3` |

| Original artifact | SHA256 |
| --- | --- |
| ProviderAdmission | `a785e02fcb52f546c1e4cf8a7a08a33e90644323d2cba8722937b99f599e6098` |
| Successful probe request | `88cfa12ac119059ae8b2295d92714160e61c40fa6c7b07c4af5faecc418f2a4c` |
| Full local CampaignFreeze | `c7ae0d5151f818b3dc190c223cf1663a5d547c1b4ef0c5771553dc50741e41c3` |

ProviderAdmission and freeze have status `ACCEPTED`, with `fixture_only = false`.
The exact freeze ID passed two local verifications and all **34/34** recorded
invariants. The real `deepseek-v4-pro` probe passed the exact R4 typed action;
its receipt accounts for 960 prompt + 50 completion = 1,010 total tokens,
0 cache-hit + 960 cache-miss = 960 prompt tokens, and 1,466 microusd at the
frozen conservative tariff. This is admission evidence, not a financial result.

## Frozen protocol

- Three initial factors yield four admissible sets, five allocators and 20
  reachable strategies. Deterministic search is exhaustive.
- Agent value is `research_efficiency_under_exhaustive_oracle`: three required
  selection runs, at least two successful runs, four deterministic oracle
  portfolio evaluations, at least one evaluation saved per successful run and
  median saving at least one. Oracle noninferiority remains required.
- Candidate gates require all three folds evaluable, zero unresolved sessions,
  mean fold 5bp return strictly positive, worst fold 5bp return at least -0.01,
  and mean fold 10bp return nonnegative.

All recorded evidence is development-only. `campaign_executed`, `r4_stage_exit`,
`independent_confirmation`, `alpha_authority`, `paper_authority`, `live_authority`
and `r5_eligible` are false. Recording or merging these files cannot run a
campaign. The next execution needs a separate local plan/authorization and the
original full freeze with current provider/source/code/environment verification.

## Preserved history and packaging checks

The 2026-09-06 admission failed with insufficient receipt evidence. An earlier
separately authorized 2026-09-07 attempt verified transport/model/usage but failed
strict action. After probe hardening, the later separately authorized attempt
passed the exact action and created the accepted admission recorded here. Each
failure remains valid historical evidence; success does not erase it. The
earlier 2026-09-07 request/failure hashes are retained in the review record.

This evidence/governance development phase made no provider call, admission,
freeze or campaign. Packaging checks recompute file SHA256 and canonical IDs,
inspect recorded verify/audit results and receipt arithmetic, compare frozen
implementation file hashes, and scan the files proposed for publication for
credential markers and absolute local paths. Existing documentation governance
and the triggered GitHub workflows validate the PR; real-provider testing is
never added to CI.

See the [R4 stage](../../../docs/development/stages/r4-agent-adaptive.md),
[backlog](../../../docs/development/backlog.md) and
[research workflow](../../../docs/guides/research-workflow.md) for the current
governance boundary.
