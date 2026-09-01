# A-share Historical v1.0 release record

Status authority: [`../status.toml`](../status.toml)  
Release state: **accepted / closed**.

This record consolidates the former A-C4/A-C5/HW-1.0 testing/changelog documents. It is the durable historical interpretation of the A-share product line; detailed implementation diffs remain in Git/PR history.

## 1. What was frozen

A-C5 is a release identity stage over an already accepted real A-share historical chain. It does not rerun Alpha research, consume reserve observations, promote a strategy, start PAPER, contact a broker or authorize live capital.

A valid real freeze requires:

```text
schema_version = finagent.ashare-historical-v1-freeze.v1
stage = A-C5
contract_valid = true
frozen = true
```

The freeze binds the release Git SHA, real A-C3 acceptance/evidence lineage, A-C4 requirement audit, content-hashed dataset manifest, A-C3 artifact identities/digests, environment/dependency identity files and the production-reserve non-consumption boundary.

## 2. Final H0 acceptance

The final operator-attested real local HW-1.0-RS run on 2026-09-01 returned:

```text
accepted = true
browser_status = passed
contract_valid = true
freeze_id = ashare-historical-v1-76ba98983c1ffc6efb4b0f9a16acd5192eb7dd6c
smoke_id = historical-workbench-rs-7ad4e7bdfa86b3551da62c6691934933bc312c73
production_reserve_consumed = false
research_outcome = NO_ROBUST_FACTOR_FAMILY
```

The exact local JSON/Markdown report remains the authority for its full artifact/Git lineage. The repository release tag is anchored to `fdea75e79122fa3d617c9862a4ee09db471b04cf`, the pre-ENG-0 closure baseline after all H0 repository-side test hardening and before dependency/runtime development begins. This tag target is a repository closure marker; it does not replace fields persisted in the local A-C5/HW reports.

Release tag:

```text
finagent-ashare-historical-v1.0
```

## 3. Reviewed research result

Historical v1.0 explicitly permits two research outcomes:

```text
POPULATED_STRATEGY
NO_ROBUST_FACTOR_FAMILY
```

The reviewed release path is `NO_ROBUST_FACTOR_FAMILY`. Therefore a valid release state includes:

```text
Strategy decision rows = 0
MarketBarSeries may be unavailable/null for a nonexistent strategy
Portfolio/Execution strategy validation is unavailable rather than fabricated
FactorSeries remains visible as rejected-candidate evidence
browser_recomputation = false
```

This is a platform/governance acceptance, not an Alpha acceptance.

## 4. A-C4 requirement audit meaning

The initial requirement audit classifies each original requirement as:

```text
PASS / PARTIAL / DEFERRED / N/A
```

Strategic deferral is not silently relabeled as implementation failure, and the A-C5 real freeze requires the final A-C4 record to be consistent with the release SHA/manifest and to contain no unresolved `PARTIAL` item under its frozen policy.

## 5. Freeze outputs

Default real artifacts:

```text
reports/finagent_ashare_historical_v1_freeze.json
reports/finagent_ashare_historical_v1_freeze.md
reports/finagent_ashare_historical_v1_freeze.zip
reports/historical_workbench_release_smoke.json
reports/historical_workbench_release_smoke.md
```

The package contains canonical freeze/A-C3/A-C4 records and verified evidence/dependency identities, not the multi-GB raw Parquet corpus. The local smoke report additionally records the exact post-freeze browser acceptance lineage.

## 6. Post-freeze Historical Workbench smoke

HW-1.0-RS validates the already frozen product against the exact local evidence and production frontend. It does not rerun A2.6/A4 or consume reserve data.

Real acceptance requires:

```text
schema_version = finagent.historical-workbench-release-smoke.v1
stage = HW-1.0-RS
contract_valid = true
browser.status = passed
accepted = true
production_reserve_consumed = false
```

The final H0 run satisfied these semantics. Repository-side Node 22 unit/type/build/Playwright contracts were also green before the real local run.

## 7. Fail-closed release boundaries

The release/smoke rejects tampered identities/digests, invalid/synthetic evidence in real mode, non-ancestral or protected historical/product drift, incomplete certification lineage, inconsistent A-C4/A-C5 records, missing original evidence, browser financial recomputation, fabricated no-alpha strategy/portfolio evidence, failed production build or failed real browser smoke.

Test-only frontend files are outside the frozen runnable product denominator; correctness test hardening after A-C5 does not by itself require rerunning the historical financial freeze.

## 8. Interpretation boundary

Historical v1.0 does **not** imply:
- persistent or deployable Alpha;
- complete survivorship/security-master correctness beyond the stated data evidence;
- complete corporate-action account ledger;
- benchmark/style/industry/capacity/risk-contribution evidence where unavailable;
- realistic intraday/order-book execution from daily-bar A-share simulation;
- external PAPER, realtime broker or live-capital readiness.

After H0 acceptance/tagging, A-share-only feature development is no longer P0 except correctness/security fixes or future adapter compatibility requirements.
