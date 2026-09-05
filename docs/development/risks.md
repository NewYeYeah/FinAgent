# Development risk register

Only active/unresolved risks belong here. Resolved implementation history belongs in the aggregate changelog, release snapshots and Git/PR history.

## P0 — blocks research correctness or downstream authority

### US-R3 regime evidence admission
The repaired panel kernel checks an explicit regime source identity and requires each label's timezone-aware availability to precede or equal formation availability. These are caller-supplied metadata, not independent authentication of the source classifier, training window or evidence graph. Financial regime evaluation still requires source-lineage admission; a fabricated past timestamp or arbitrary policy/evidence string must not become research authority. The label-blind usability operator does not enable regime gates or financial evaluation.

### US-R3 declared versus enforced research boundary
The v1 proposal validator checks a submitted slot/round in isolation, not cumulative use across calls. It has no persistent run ledger or model tool-dispatch boundary. Static `*_authority=false` payloads and a no-MT5-import test do not establish information isolation or runtime quota enforcement. Generation/evaluation must wait for durable slot reservation, strict decoding, scoped data/tools/memory, idempotent resume and quota failure tests.

### Independent evidence depletion and test power
New hypotheses designed after R2 are exposed to the R2 corpus at the research-program level. Renaming old folds or changing provider does not restore independence. Later calendar dates alone also do not prove non-exposure. Record data/model/publication exposure and reserve a prospective or demonstrably sealed evaluation; freeze sample/power and stop rules before final outcomes, and distinguish insufficient evidence from a negative or positive strategy result.

### Intraday clock and calendar correctness
DST, holidays, half-days, session boundaries, extended hours and bar timestamp convention can create leakage or incorrect resampling/labels. US-C0/US-D3 are blocking gates.

### Corporate-action and price-basis semantics
The selected OHLCV-1m source is treated as raw/split-unadjusted intraday history. Split/dividend events are not embedded in the OHLCV rows. Research that spans action discontinuities must attach explicit action evidence/transform policy or exclude affected windows; silently treating raw intraday prices as a continuous adjusted series is forbidden.

### Survivorship / universe bias
The minute corpus contains historical ticker observations but does not provide a point-in-time security master/lifecycle table. The present MT5 CFD intersection is also an EngineeringUniverse, not a historical PIT universe. Formal market-wide Alpha claims require lifecycle/PIT evidence or an explicit limited interpretation.

### Conflicting duplicate market bars
Exact duplicate full rows are deterministic to collapse, but two different OHLCV observations for the same `(ticker,timestamp)` have no safe generic winner. Sampled conflicting duplicate keys remain a fail-closed condition until a source-specific reconciliation rule with evidence exists.

### Overlapping intraday labels / invalid inference
Minute observations are serially dependent and forward horizons can overlap. Purging, HAC and block/session bootstrap must replace IID assumptions in formal research.

### Search denominator / Agent multiplicity
Manual, programmatic and Agent search must retain the frozen denominator required by the experiment. Failed/weak Agent trials do not disappear from multiplicity accounting.

### Research-to-CFD identity mismatch
Listed equity bars and broker CFD instruments differ in contract size, volume units, sessions, margin and swap. A ticker string is not a sufficient mapping.

### Broker/realtime state reconciliation
Internal order/position/account state must reconcile to broker order/deal history. Unknown drift, stale data or restart ambiguity must fail closed before external authority grows.

## P1 — record explicit limitation and continue only when the stage permits

### Broad local regression baseline and timezone portability
The local full-suite run accompanying R3 numeric usability recorded 13 failures outside the changed R3 surface: nine historical A-share compliance/freeze tests still reference removed versioned planning documents in `configs/acceptance/ashare_initial_requirement_compliance_ac4.toml`; four U.S. D2 tests assert UTC text against DuckDB timestamps displayed in the workstation's `+08` timezone. The old compliance references already exist at `629df86`, and the affected D2 implementation/tests were not changed by this increment. Do not describe the full local suite as green or silently recreate obsolete active plans. Repair historical reference ownership and make timestamp assertions timezone-explicit in a separate compatibility increment; do not reinterpret accepted financial evidence. The 156 focused A1/R2/R3 regressions and dedicated Linux/Windows usability CI passed.

### U.S. minute source publication / redistribution rights
The Hugging Face dataset README does not declare a license and the upstream Finnhub acquisition/redistribution chain is not independently verified. For FinAgent's current **local, non-redistributed research** scope this is recorded as a limitation rather than a blocker after an exact local snapshot passes certification. Any redistribution, hosted dataset publication or stronger public provenance claim requires a separate rights review.

### Local minute snapshot integrity
The local corpus is large enough that accidental partial downloads, wrong Hugging Face revisions or missing monthly partitions are plausible. The local certification gate binds the exact revision, inventories all monthly files and scans selected partitions before research admission.

### Sparse market-data defects and cleaning-policy drift
Real certification observed extremely sparse invalid OHLC rows and duplicate keys. FinAgent permits bounded deterministic quarantine/collapse rather than requiring a mathematically perfect 80+ GB corpus. The thresholds and actions are identity-bound in `MinuteDataCleaningPolicy`; changing a threshold changes `policy_id` and certification identity. Thresholds must not be loosened ad hoc to make a failing dataset pass. Outside-session observations remain diagnostic unless a later session contract proves them invalid.

### Minute Data Plane runtime and memory pressure
Parquet scans are out-of-core but bounded research windows, feature matrices and inference may still exceed memory. Instrument scan/materialization budgets and profiling are required before scaling the universe.

### Provider/broker entitlement variation
Historical depth, realtime feed quality and symbols depend on account/broker/terminal configuration. Capability evidence is environment-specific and must not be promoted to universal provider claims.

### Cross-source differences
Equity history and CFD broker bars/ticks may differ legitimately. Reconciliation must distinguish expected instrument/source differences from defects rather than force equality.

### Transaction-cost model uncertainty
Current spread/slippage samples may not represent historical or stressed execution. Cost assumptions require versioned scenarios and sensitivity analysis before economic acceptance.

### Agent cost / instability
LLM provider/model changes can alter candidate output, latency and cost. Agent experiments bind model/provider/prompt identity and use repeated runs rather than one anecdotal result.

## P2 — deployment hardening

- secure secret isolation and broker credential handling;
- physical/cryptographic separation for sealed or operational evidence;
- high-availability feed/broker connectivity;
- incident response under network partition, duplicate/partial fills and broker outages;
- operational monitoring/SLOs;
- live-capital jurisdiction/account-specific review;
- optional future QMT adapter acceptance.

## Historical A-share note

A-share Historical v1.0 may close with a reviewed no-alpha result. Its limitations (security-master completeness, daily-fill realism, corporate-action account ledger, benchmark/capacity/risk-attribution gaps) are historical release interpretation, not reasons to continue adding A-share-only P0 features to the new U.S./MT5 development line.
