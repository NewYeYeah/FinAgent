# A-C3 Real A-share Historical E2E Acceptance

Status: **Implementation complete / real local-data acceptance pending**  
Stage: **A-C3 — Real A-share Historical E2E Acceptance**  
Planning authority: [`current-development-plan-v4.0.md`](current-development-plan-v4.0.md)  
Next stage after a real `accepted=true` result: **A-C4 — Initial Requirement Compliance Audit**

## Purpose

A-C3 is not another architecture-expansion milestone. Its purpose is to prove that the accepted A-share historical system can run as one identity-consistent product on the real frozen local dataset:

```text
local dataset certification
→ development research
→ A2.6 robust research
→ A4 execution-aware validation
→ FactorSeries
→ StrategyDecisionSeries
→ MarketBarSeries
→ Historical Workbench
→ review bundle
→ A-C3 acceptance record
```

The stage is deliberately split into two different notions of success:

```text
implementation / CI contract validity
            !=
real local-data acceptance
```

A GitHub CI fixture can validate the orchestration/verifier contract, but it can never close A-C3. The final stage transition requires a local run against the frozen A-share Parquet dataset with full content verification.

## Why GitHub CI cannot close A-C3

The repository contains configuration references to the user-owned local dataset, including:

```text
D:/Data/A-Share
```

and the frozen manifest path used by research configs:

```text
data/manifests/local_ashare_daily.json
```

The actual A-share Parquet files and frozen manifest are not committed to the repository and are therefore unavailable to the Ubuntu GitHub runner.

A-C3 consequently refuses the misleading pattern:

```text
synthetic CI fixture passes
→ claim real A-share historical acceptance
```

Instead the acceptance record exposes:

```text
contract_valid
accepted
real_dataset_attested
```

For CI:

```text
contract_valid = true   # allowed
accepted = false        # mandatory
real_dataset_attested = false
```

Only the real local run may produce `accepted=true`.

## Real historical acceptance runner

Implemented in:

```text
src/finagent/runtime/ashare_historical_acceptance.py
scripts/run_ashare_historical_acceptance.py
configs/acceptance/ashare_historical_e2e.example.toml
```

The runner consumes the existing reviewed application services rather than creating a new financial calculation authority.

Application-service stages:

```text
data.certify_local_ashare
research.run_development
research.run_a2p6
portfolio.run_a4
review.export_bundle
```

Every stage is persisted through a dedicated `SQLiteCommandStore` as:

```text
CommandIntent
→ planned
→ running
→ succeeded / rejected / failed
→ CommandResult
→ evidence_ids / artifact_paths
```

The runner checks the frozen Historical Control catalog before execution:

- only L0/L1 commands are accepted;
- every command must be `application_service_ready`;
- the catalog binding must equal `HISTORICAL_APPLICATION_SERVICE_BINDINGS`;
- commands that require confirmation require `--confirm`;
- a ConfigSnapshot must belong to an allowlisted descriptor;
- redacted ConfigSnapshots are rejected rather than silently executing with missing secrets.

A-C3 adds no reserve, promotion, PAPER, broker, realtime or live-capital command authority.

## Cross-config preflight

Before any expensive research starts, the runner requires the development, A2.6 and A4 configs to resolve to the same:

```text
dataset root
frozen manifest
```

It also requires the A4 config's `a2p6_report` to be the exact report path produced by the configured robust A2.6 stage.

This prevents an expensive run from finishing with internally unrelated historical evidence.

## A-C2 integration defect found by A-C3

A-C3 exposed a real integration defect that synthetic A-C2 tests could not reveal.

Before A-C3, `scripts/materialize_local_ashare_market_bars.py` let `LocalAshareParquetDataAdapter` create its normal fast-fingerprint `data_version`:

```text
local-ashare-1d-fast-...
```

while A2.6/A4/StrategyDecisionSeries use:

```text
LocalAshareFrozenManifest.dataset_version
```

Because A-C2 correctly requires exact `data_version` identity, a real MarketBarSeries would have been rejected even when reading the same physical dataset.

A-C3 fixes this by making the MarketBar materializer require:

```text
--frozen-manifest <path>
```

It now:

1. loads the frozen manifest;
2. verifies that the requested frequency is in the manifest;
3. verifies the local dataset against the frozen manifest;
4. requires `frozen.dataset_version == StrategyDecisionSeries.data_version`;
5. constructs the market-bar adapter using that frozen `dataset_version`;
6. persists the same version in MarketBarSeriesEvidence.

For final A-C3 closure the materializer is called with `--verify-content`.

## Host-side V4 materialization

After A4 succeeds, A-C3 invokes the already-frozen deterministic host materializers:

```text
materialize_factor_series.py
materialize_strategy_decision_series.py
materialize_local_ashare_market_bars.py
```

They are not added to the generic Control Plane.

They are invoked with Python argv arrays:

```text
[sys.executable, script, arg1, arg2, ...]
```

not shell command strings. This avoids creating arbitrary shell/Python authority while preserving the existing deterministic materialization boundary.

## Acceptance verifier

`verify_ashare_historical_acceptance(...)` reopens the full evidence chain using the normal verified projections:

```text
StrategyDecisionSeriesProjection
FactorSeriesProjection
MarketBarSeriesEvidence
Workspace / Strategy / Factor / Portfolio / Execution projections
SQLiteCommandStore
review bundle ZIP
```

It does not trust filenames or the runner's in-memory objects after the run.

### Dataset / code identity

A real accepted run requires:

- non-empty exact `git_sha`;
- frozen daily A-share dataset manifest;
- `frozen.verify(..., verify_content=True)`;
- frozen dataset version equals the A2.6/A4/V4 data version.

Metadata-only frozen-manifest verification cannot set `accepted=true`.

### Certification / research chain

Required checks include:

- certification schema is `finagent.local-ashare-certification.v1`;
- certification `passed=true`;
- development report is `finagent.ashare-factor-research-acceptance.v2`;
- development system completion passed;
- development reserve remains `untouched`;
- development and robust data versions match;
- A2.6 program is `frozen`;
- A2.6 system acceptance passed;
- A2.6 reserve remains `untouched`;
- A4 system acceptance passed;
- A4 reserve remains `untouched`;
- A4 binds the exact robust program result and data version.

### V4 evidence identity

Required checks include:

- StrategyDecisionSeries is verified and non-empty;
- Strategy binds the exact A4 validation, A2.6 result and data version;
- FactorSeries is verified and non-empty;
- FactorSeries binds the exact A2.6 result/data version;
- MarketBarSeries is verified, daily and non-empty;
- MarketBarSeries binds exact Strategy/A4/data-version identities.

### Workbench acceptance

The verifier creates the normal Evidence Plane and requires:

- Strategy resolves the exact StrategyDecisionSeries;
- Strategy resolves the exact MarketBarSeries;
- Factors resolve the exact FactorSeries;
- Portfolio/Execution resolve the exact StrategyDecisionSeries for the A4 validation;
- linked analytics acceptance remains true;
- browser recomputation remains false;
- missing-evidence policy remains `explicit_unavailable_not_inferred`;
- all eight WorkbenchContext identity keys remain declared;
- every `/api/v4/` route remains GET/HEAD/OPTIONS-only.

### CommandRun → Evidence trace

The verifier requires exactly one succeeded acceptance-run CommandRun for each required command and checks that:

- development CommandRun records the development `acceptance_id`;
- A2.6 CommandRun records the robust `program_result_id`;
- A4 CommandRun records the `portfolio_validation_id`;
- review export records the same validation identity.

### Review bundle

The final review bundle must be a non-empty valid ZIP generated from the same evidence roots.

## Acceptance record

The final report schema is:

```text
finagent.ashare-historical-e2e-acceptance.v1
```

It records:

```text
acceptance_id
stage
mode
contract_valid
accepted
real_dataset_attested
git_sha
dataset provenance / content-verification state
all canonical evidence identities
all acceptance checks
CommandRun records
V4 route methods
linked-analytics projection
artifact paths / SHA-256 / sizes
```

The `acceptance_id` is content-addressed from the code/data/evidence identities and acceptance results.

## CI contract fixture

Ubuntu CI uses mode:

```text
ci_contract_fixture
```

It composes a complete verified V4 evidence graph and durable five-command audit chain, then runs the same acceptance verifier.

The expected CI result is explicitly:

```text
contract_valid = true
accepted = false
real_dataset_attested = false
```

The test fails if CI is ever able to promote its synthetic fixture to `accepted=true`.

## Blocking test environment

Per the frozen development-efficiency policy, A-C3 uses only:

```text
Ubuntu latest
Python 3.11
```

for the Python blocking gate.

The Workspace gate includes:

- focused backend V1/V2/V3/V4/A-C1/A-C2/A-C3 regression;
- `py_compile` for A-C3 and existing Workbench entry points;
- Ruff;
- typed-boundary mypy including the A-C3 runner/verifier;
- `pip check`;
- existing frontend TypeScript/Vitest/build/Playwright regression.

No Windows Workspace API matrix is reintroduced.

## Final local closure command

Before the real run:

1. ensure `D:/Data/A-Share` and the frozen manifest paths in the three historical configs are correct;
2. set `git_sha` in `configs/acceptance/ashare_historical_e2e.example.toml` to the exact commit checked out for the run;
3. keep `verify_content = true`;
4. confirm that A4's `a2p6_report` is the same report produced by the robust config.

Then run:

```powershell
python scripts/run_ashare_historical_acceptance.py configs/acceptance/ashare_historical_e2e.example.toml --confirm
```

A-C3 is closed only when:

```text
reports/ashare_historical_acceptance_ac3.json
```

contains:

```json
{
  "contract_valid": true,
  "real_dataset_attested": true,
  "accepted": true
}
```

## Current completion rule

At merge time, A-C3 implementation and the Ubuntu/Python 3.11 contract gate may be complete while the stage itself remains **current**.

Do **not** advance to A-C4 until a real local-data acceptance report with `accepted=true` exists and its Git/evidence identities are recorded.
