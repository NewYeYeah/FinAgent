# Accepted R4 matched v3 campaign result

This directory records a **previously completed offline R4 matched campaign** that
was independently reviewed with disposition `R4_RESULT_ACCEPTED`. It is a
repository-safe evidence reference only. Nothing in this directory executes
research, calls a provider, regenerates admission/freeze artifacts, or replaces
the original immutable local campaign artifacts.

The accepted host terminal is `NO_ADAPTIVE_CANDIDATE`; Agent value is
`INCONCLUSIVE`. These statements are simultaneously valid under the frozen
`r4-matched-v3` protocol because Agent-value completeness and Candidate Gate
viability are separate deterministic-host gates.

## Evidence ownership

| File | Meaning |
| --- | --- |
| [campaign_result_attestation.json](campaign_result_attestation.json) | Exact identity/hash reference and accepted aggregate campaign facts; not the original `campaign_result.json` |
| [campaign_evidence_review.json](campaign_evidence_review.json) | Repository-safe record of the independently accepted result review |
| [resource_summary.json](resource_summary.json) | Accepted provider/token/cost and portfolio-evaluation accounting |

The original `campaign_result.json`, full campaign directory, databases, model
messages and other local execution artifacts are not reconstructed here. The
accepted CampaignResult identity is
`r4-campaign-result-d32ec253d62eb4f9349896b0` with SHA256
`5f9cb2b687f5b5750255c4d91e6db273fdf2577a8ce71f33365cddf19789c8ac`.
The accepted review bundle SHA256 is
`5e387790ec9b6d3198a2439c02900c1817d742de1b123c854f2ca31d4328c69d`.

## Accepted interpretation

Exactly one real matched campaign invocation completed, with no automatic retry,
no rerun and no provider fallback. The seven completed runs were deterministic,
three Primary selection runs and three discovery runs. Artifact binding audit was
44/44 PASS. The campaign directory contained 46 files because the freeze and
final result sit outside the 44 pre-result bound-artifact digest set.

The deterministic Primary search structurally covered all 4 factor sets x 5
allocators = 20 strategies. However, **0/20** deterministic strategies had
complete economic evidence under the frozen three-fold completeness rule:
`evaluable_folds = 0/3` for every deterministic strategy and unavailable-session
counts ranged from 39 to 64. Across all 30 Primary candidate rows, zero were
complete. Therefore `deterministic_evidence_complete = false` and no deterministic
economic oracle could be constructed.

This makes Agent value `INCONCLUSIVE` even though the three Primary runs saved a
median of three portfolio evaluations relative to the four-evaluation
deterministic schedule. There were zero successful Agent runs under the frozen
oracle-efficiency rule. The result is **coverage/completeness-driven
`NO_ADAPTIVE_CANDIDATE`**, not evidence that all strategies lost money and not a
claim that Agent economic performance was proven negative.

The campaign is also not `SYSTEM_FAILURE`. Deterministic evaluations completed as
`PORTFOLIO_EVALUATED`, all required Primary runs completed, and discovery-03 ended
`SLOT_ATTEMPTS_EXHAUSTED`, an admitted normal run terminal. The deterministic
host therefore validly emitted `NO_ADAPTIVE_CANDIDATE` with `candidate_id = null`.
No development candidate artifact or AdaptiveStrategy exists.

## Reliability and authority

The real Agent runs recorded 62 rejected action attempts. Discovery-03 consumed
48 provider calls, ended `SLOT_ATTEMPTS_EXHAUSTED`, and retained 44 rejected
actions, including 43 `candidate_not_proposed_in_run` rejections. This is not a
ProviderAdmission failure; it is retained as evidence that complex autonomous
tool-use reliability remains materially imperfect.

All result authority remains development-only:

- independent confirmation: false;
- Alpha authority: false;
- PAPER authority: false;
- Live authority: false;
- R5 eligibility: false.

Accordingly B-006 may close because the frozen matched-campaign limitation has
been resolved by an accepted terminal result. That closure is not Alpha success.
There is no AdaptiveStrategy, so R5 does not start. A future research attempt must
be a new versioned R4 cycle rather than a result-driven rerun of this campaign.
WORKBENCH-2 productization remains permitted by the current roadmap.

See the [R4 stage](../../../docs/development/stages/r4-agent-adaptive.md),
[backlog](../../../docs/development/backlog.md),
[testing strategy](../../../docs/testing/strategy.md) and
[research workflow](../../../docs/guides/research-workflow.md) for canonical
governance.
