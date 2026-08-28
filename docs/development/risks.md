# Development Risk Register

Only active risks are listed here. Resolved implementation history belongs in the changelog and Git history.

## P0 — blocks research correctness

### A-share timestamp/price semantics

Status: partially resolved.

Daily and audited 1-minute semantics are frozen. 5/15/30/60-minute data remain disabled by default until representative samples verify bar boundaries.

### Dataset and protocol identity drift

Local vendor data is external and large. Research must bind the frozen manifest, candidate universe, ResearchProgram, factor family, A3 execution assumptions, A4 specification and execution-ledger digest. A changed file or rule set cannot silently reuse prior evidence identity.

### Split/reserve leakage

Forward labels must stay inside split boundaries. A4 test calendars use a feature-only adapter and must not read a future reserve row. The 2025+ reserve is one-shot and cannot be reused for adaptive research.

### Search denominator or frozen-factor mutation

All searched factors must remain in the A2.6 denominator. A4 may use only the frozen robust factor digests, directions and weights; it cannot reselect or reverse them from portfolio results.

### Accounting and exact replay

Cash, positions, T+1 inventory, fees and NAV must conserve across every cycle. A4 report and JSONL execution ledger must replay exactly. Approximate replay is not accepted as a substitute for deterministic ordering and stable aggregation.

## P1 — record and continue with explicit limitation

### Incomplete A-share security master

Vendor `delist_date`/`list_status` coverage is incomplete. Current universe is candidate-only. Supplemental delisting/status files may improve coverage but must remain independently versioned and must state their coverage.

### Historical ST/suspension/price-limit coverage

Daily vendor rows expose status and limit fields, and A3 handles exact-session rows conservatively, but complete historical event semantics are not certified. Avoid claims that A4 is a fully survivorship- and tradability-correct market study.

### Daily-bar fill realism

A3/A4 use conservative exact-open fills and block one-sided limit states. They do not model queue priority, intraday reopening, partial fills or order-book depth. This can over- or understate realizable execution depending on the scenario.

### Capacity and market impact

A4 full-day volume participation is ex-post diagnostic only and does not decide fills. Before reserve or PAPER, define a preregistered lagged-liquidity/impact model and explicit capacity gate.

### Corporate-action cash/event accounting

Research returns use adjustment-aware prices while execution uses raw prices. A4 does not yet maintain a complete dividend, split, rights-issue and cash-distribution event ledger. Long-horizon economic returns require this extension or an explicit exclusion policy.

### Benchmark, industry and style exposure

The first A4 optimizer is long-only with asset caps and target cash, but does not yet constrain benchmark beta, sector concentration or style exposure. Apparent Alpha may include unintended market/industry bets.

### Fee schedule applicability

Broker commission, minimum commission and pass-through assumptions are configurable and account-specific. A single schedule must not be presented as universally valid across accounts and historical periods.

### Large-panel runtime and memory pressure

Parquet scanning is out-of-core, but feature panels, risk windows and ledgers still materialize in memory. Full A-share × long history × many factors may require chunked study orchestration and cached immutable panels.

### Secondary provider instability

AKShare depends on upstream public websites and local proxy/network behavior. Failure of this secondary source must not block the primary local A-share or Alpaca SIP research path.

### Cross-store crash consistency

Some research/operational state transitions cross SQLite stores and are recoverable rather than globally transactional.

## P2 — deployment hardening

- physical separation of sealed data;
- cryptographic/HSM-backed evidence sealing;
- general process information-flow controls;
- production external broker connectivity;
- high-availability realtime feed/reconciliation infrastructure;
- incident recovery under partial fills, disconnects and stale provider state.

## Current A-share operational decision

Realtime A-share validation and live-capital operation are deferred. Expensive realtime or complete historical-status products are not a prerequisite for the current historical research milestone. The next permitted evidence step is unified A2.6/A3/A4 acceptance, followed only then by a separately authorized one-shot reserve protocol.
