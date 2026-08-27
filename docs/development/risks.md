# Development Risk Register

Only active risks are listed here. Resolved implementation history belongs in the changelog and Git history.

## P0 — blocks research correctness

### A-share timestamp/price semantics

Status: partially resolved.

Daily and audited 1-minute semantics are frozen. 5/15/30/60-minute data remain disabled by default until representative samples verify bar boundaries.

### Dataset identity drift

Local vendor data is external and large. A stable frozen manifest is required so a local file replacement cannot silently reuse prior evidence identity.

### Split/holdout leakage

Forward labels must stay inside split boundaries. Sealed holdout is one-shot and cannot be reused for adaptive research.

### Search denominator mutation

All searched factors and the frozen ensemble must remain in the formal evidence denominator.

## P1 — record and continue with explicit limitation

### Incomplete A-share security master

Vendor `delist_date`/`list_status` coverage is incomplete. Current universe is candidate-only. Supplemental delisting/status files may improve coverage but must remain independently versioned and must state their coverage.

### Historical ST/suspension/price-limit coverage

Daily vendor rows expose some status fields, but complete historical event semantics are not yet certified. Avoid claims that backtests fully model A-share tradability.

### Large-panel memory pressure

Parquet scanning is out-of-core, but `ResearchSplit` materialization is still a NumPy panel. Full A-share × long history × many features can exceed memory. Use bounded universes/date ranges until chunked panel storage is implemented.

### Secondary provider instability

AKShare depends on upstream public websites and local proxy/network behavior. Failure of this secondary source must not block the primary local A-share or Alpaca SIP research path.

### Cross-store crash consistency

Some research/operational state transitions cross SQLite stores and are recoverable rather than globally transactional.

## P2 — deployment hardening

- physical separation of sealed data;
- cryptographic/HSM-backed evidence sealing;
- general process information-flow controls;
- production external broker connectivity;
- high-availability realtime feed/reconciliation infrastructure.

## Current A-share operational decision

Realtime A-share validation and live-capital operation are deferred. Expensive realtime or complete historical-status products are not a prerequisite for the current historical research milestone.
