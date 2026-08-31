# A-C4 — Initial Requirement Compliance Audit

Status: **Implementation complete / focused CI required before merge**

A-C4 converts the Historical v1.0 requirement review into a deterministic, repository-verifiable audit artifact.

## Delivered

The frozen manifest is:

`configs/acceptance/ashare_initial_requirement_compliance_ac4.toml`

It contains the 22 minimum requirements frozen by the v4.0 planning baseline. Initial Historical v1.0 classification is:

```text
PASS     15
DEFERRED  7
PARTIAL   0
N/A       0
```

Strategic deferral is explicit rather than represented as an implementation failure.

The machine-verifiable runtime is:

`src/finagent/runtime/initial_requirement_compliance.py`

It validates the exact requirement denominator, status vocabulary, repository-local source/implementation/test references, manifest SHA-256 and exact Git SHA. Every PASS row must bind both implementation and test/evidence references. The generated `audit_id` changes whenever the frozen manifest, classifications, references or Git identity changes.

The CLI is:

`scripts/run_initial_requirement_compliance_audit.py`

Default outputs:

```text
reports/ashare_initial_requirement_compliance_ac4.json
reports/ashare_initial_requirement_compliance_ac4.md
```

The report exposes:

```text
audit_complete
historical_freeze_ready
status summary
deferred capability IDs
manifest identity
Git identity
production_reserve_authority = false
reserve_accessed_by_audit = false
```

## PASS scope

Historical v1.0 closes the implemented and accepted historical capabilities for PIT data/ResearchDataset, bounded Agent research, A2.6 robust research, A3 A-share execution, A4 execution-aware portfolio validation, immutable evidence/replay, A5 one-shot infrastructure, Evidence/Governance, Workbench Foundation, Strategy/Factor/Portfolio/Execution analytics, V4 linked acceptance, Historical Workbench L0/L1 execution and provider-neutral OHLC evidence.

A5 infrastructure being PASS does not imply production reserve use. v4.0 D6 remains unchanged.

## DEFERRED scope

The following remain outside A-share Historical v1.0 by strategy:

- authoritative benchmark and benchmark-relative evidence;
- explicit provider-neutral corporate-action/cash-event evidence;
- capacity/market-impact modelling;
- advanced style/industry/risk-contribution analytics;
- A-share PAPER operational deployment;
- provider-neutral realtime gateway/event implementation;
- QMT gateway implementation.

Existing adjacent primitives do not upgrade these items to PASS without their missing evidence or deployment contract.

## Acceptance

Focused acceptance is documented in:

`docs/testing/ac4-initial-requirement-compliance.md`

Required terminal properties are:

```text
audit_complete = true
historical_freeze_ready = true
PASS = 15
DEFERRED = 7
PARTIAL = 0
N/A = 0
```

`.github/workflows/ac4.yml` uses Ubuntu/Python 3.11 and covers focused pytest, report generation, `py_compile`, Ruff, mypy and dependency consistency. A-C4 remains a read-only compliance layer with no reserve, PAPER, broker or live-capital authority.

## A-C5 handoff

A-C5 should bind the merged-main Git SHA and generated A-C4 `audit_id` instead of copying the requirement matrix into a second hand-maintained source.
