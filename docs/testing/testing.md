# Testing and System Acceptance

This is the canonical test guide. Tests verify implementation, data contracts and research invariants; they do not prove that an alpha will persist.

## 1. Release gate

Every merge must keep the following green:

```text
Ubuntu Python 3.11 / 3.12 / 3.13 pytest
Windows Python 3.11 pytest
critical Ruff checks
targeted mypy
coverage floor
package build
pip dependency consistency
```

Ubuntu:

```bash
./scripts/finagent.sh python -m pytest -q
```

Windows PowerShell:

```powershell
$env:PYTHONUTF8 = "1"
$env:PYTHONNOUSERSITE = "1"
python -m pytest -q
```

`pytest.ini` blocks environment-level ROS2 and Phoenix plugins that FinAgent does not
use. This is intentional: an incompatible optional `arize-phoenix` installation must
not be able to crash FinAgent before test collection. For maximum isolation you may
still set `$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = "1"`; CI does so explicitly.

Static/package checks:

```bash
ruff check src tests scripts --select E9,F63,F7,F82
mypy src/finagent/data src/finagent/research
python -m pytest --cov=finagent --cov-report=term --cov-fail-under=50
python -m build
python -m pip check
```

## 2. Provider smoke tests

LLM connectivity:

```bash
python scripts/smoke_llm_provider.py configs/llm.toml --profile deepseek_official_v4_pro
```

US reference data:

```bash
python scripts/pull_market_data.py configs/markets/us_etf_agent_data_alpaca.toml --show-capabilities
python scripts/validate_market_data.py data/market/us_etf_alpaca
```

Use Alpaca SIP for US historical research. IEX is a single-exchange smoke feed and may have calendar gaps.

## 3. Local A-share test sequence

Install the local Parquet surface:

```bash
python -m pip install -e ".[local-parquet]"
```

Run T-A0 through T-A4 in order.

### T-A0 — source certification

Ubuntu:

```bash
python scripts/certify_local_ashare_data.py \
  configs/local_ashare.example.toml \
  --root /data/A-Share \
  --sample-symbol 000001.SZ \
  --sample-date 2009-01-05
```

Windows:

```powershell
python scripts/certify_local_ashare_data.py `
  configs\local_ashare.example.toml `
  --root D:\Data\A-Share `
  --sample-symbol 000001.SZ `
  --sample-date 2009-01-05
```

Review the JSON, not only the exit code. It must expose schema, duplicates, invalid listing dates, incomplete status coverage, quarantined legacy codes, OHLC/adjustment quality, the 241-row minute convention and daily/minute unit reconciliation.

The audited no-trade placeholder is narrowly defined as:

```text
open = high = low = 0
close = pre_close > 0
vol = amount = 0
```

It remains in immutable vendor data, is reported as `LA-DAILY-07`, and is excluded from `PriceBar`. Any other non-positive or inconsistent OHLC remains an error.

### T-A1 — freeze the source identity

Ubuntu:

```bash
python scripts/freeze_local_ashare_data.py \
  --root /data/A-Share \
  --frequency 1d \
  --output data/manifests/local_ashare_daily.json
```

Windows:

```powershell
python scripts/freeze_local_ashare_data.py `
  --root D:\Data\A-Share `
  --frequency 1d `
  --output data\manifests\local_ashare_daily.json
```

The default computes SHA-256 for `stock_basic_data.parquet` and `stock_daily.parquet`. Keep the manifest with every research report. Use `--fast` only for diagnostics.

### T-A2 — supplemental reference data

Tracked source-bound templates live under `reference_data/a_share/`.

```bash
python -m pytest -q tests/test_ashare_freeze_supplemental_v127.py
```

Every real row must use a registered source, canonical `ts_code`, exact URL and timezone-aware `observed_at`. Partial files must remain marked `coverage = "partial"`.

### T-A3 — adapter/system smoke

Copy and edit:

```text
configs/research/local_ashare_research_smoke.example.toml
```

Ubuntu:

```bash
python scripts/run_local_ashare_research_smoke.py \
  configs/research/local_ashare_research_smoke.local.toml \
  --verify-content
```

Windows:

```powershell
python scripts/run_local_ashare_research_smoke.py `
  configs\research\local_ashare_research_smoke.local.toml `
  --verify-content
```

This verifies:

```text
frozen identity
→ supplemental master
→ DuckDB local adapter
→ strict no-trade filtering
→ ResearchDataset / eligibility_mask
→ adjustment-aware lagged features
→ common-panel-session forward labels
→ deterministic RankIC diagnostic
```

`forward_*_h` uses the common panel session clock. If the asset is not tradable on the h-th later panel session, the label is `NaN`; it must not jump to the first post-suspension trade.

The RankIC here is a plumbing diagnostic, not promotion evidence.

### T-A4 — bounded Factor Quant acceptance (A2)

The A2 entry point is:

```text
scripts/run_local_ashare_factor_research.py
configs/research/local_ashare_factor_research.example.toml
```

It performs historical daily factor research only. It does not invoke A-share execution, promotion, sealed holdout, PAPER, realtime or broker code.

#### T-A4.1 Prepare a local config

Windows:

```powershell
Copy-Item `
  configs\research\local_ashare_factor_research.example.toml `
  configs\research\local_ashare_factor_research.local.toml
```

Ubuntu:

```bash
cp configs/research/local_ashare_factor_research.example.toml \
   configs/research/local_ashare_factor_research.local.toml
```

Edit at least:

```toml
root = "D:/Data/A-Share"
frozen_manifest = "data/manifests/local_ashare_daily.json"
supplement_root = "reference_data/a_share"
state_dir = ".finagent/local-ashare-factor-a2"
report_path = "reports/local_ashare_factor_research_a2.json"
```

The example fixes a candidate universe before development, uses 2018–2021 for development, 2022–2024 for validation, and leaves 2025 onward untouched.

#### T-A4.2 Deterministic baseline

Windows:

```powershell
python scripts/run_local_ashare_factor_research.py `
  configs\research\local_ashare_factor_research.local.toml `
  --mode deterministic `
  --verify-content
```

Ubuntu:

```bash
python scripts/run_local_ashare_factor_research.py \
  configs/research/local_ashare_factor_research.local.toml \
  --mode deterministic \
  --verify-content
```

The command traverses:

```text
content-verified frozen Parquet
→ fixed pre-development candidate universe
→ per-session PIT universe policy with hidden pre-split liquidity warm-up
→ panel-native generated-feature materialization
→ Factor Quant v2 development diagnostics
→ deterministic redundancy-aware factor selection
→ frozen weights and development directions
→ independent validation of every searched factor
→ validation of the frozen factor ensemble
→ untouched reserve record
```

Acceptance checks:

- candidate universe meets configured minimum size;
- candidate selection date precedes development;
- development, validation and reserve do not overlap;
- reserve remains `untouched`;
- all generated factor digests are retained in both development and validation denominators;
- validation does not change factor weights or directions;
- split summaries report non-empty warm-up history and a non-artificial first-session eligibility count;
- Factor Quant reports contain finite IC/ICIR, quantile and turnover diagnostics;
- stability reports contain rolling/yearly RankIC, HAC, deterministic block bootstrap, monotonicity, turnover/coverage stability and Holm/BH adjustments;
- `passed = true` and `system_acceptance.passed = true` mean workflow completion only; inspect `research_outcome` for factor validity;
- signed validation deltas use the direction frozen in development; absolute-magnitude deltas are separately named;
- no execution-cost or broker claim appears in the report, and `promotion_eligible` remains false.

#### T-A4.3 Exact replay

Windows:

```powershell
python scripts/run_local_ashare_factor_research.py `
  configs\research\local_ashare_factor_research.local.toml `
  --frozen-report reports\local_ashare_factor_research_a2.json `
  --assert-replay `
  --verify-content `
  --report reports\local_ashare_factor_research_a2_replay.json
```

The `acceptance_id`, candidate denominator, development/validation Factor Quant and stability reports, frozen ensemble and research verdict must match exactly. Replay must not call the LLM. Reports produced before schema v2 must be regenerated before using `--assert-replay`.

#### T-A4.4 Agent discovery and robustness

Only after deterministic baseline and replay pass:

```powershell
python scripts/smoke_llm_provider.py configs\llm.toml --profile deepseek_official_v4_pro
python scripts/run_local_ashare_factor_research.py `
  configs\research\local_ashare_factor_research.local.toml `
  --mode agent `
  --llm-profile deepseek_official_v4_pro `
  --verify-content `
  --report reports\local_ashare_factor_research_a2_agent.json
```

The A2 example uses a 50,000-token completion ceiling for DeepSeek V4-Pro high-thinking calls. This is a ceiling, not expected usage. The provider response is authoritative for actual token consumption.

The Agent generation path has three bounded resilience layers:

```text
provider transient / JSON-mode empty content
→ provider retry (configs/llm.toml)

invalid JSON / forbidden AST / sandbox runtime failure
→ candidate conformance repair

repair budget exhausted
→ bounded replacement of the same logical candidate slot
```

Successful candidate slots are checkpointed under `state_dir`. Restarting the same scoped A2 task must reuse the exact artifact and must not spend another LLM request for already accepted slots.

Agent mode must satisfy:

- at least two discovery rounds;
- round 2 receives `DEVELOPMENT-ONLY FACTOR QUANT FEEDBACK V2`;
- candidate digests/feature IDs are unique across rounds;
- all accepted adaptive candidates remain in the final denominator;
- engineering repair feedback contains no market validation/holdout evidence;
- Agent feedback contains development metrics only;
- validation, reserve, promotion, PAPER and live evidence are absent from Agent prompts;
- hidden `reasoning_content` is never persisted;
- frozen replay succeeds without another LLM request.

A provider error containing `finish_reason=length` means the configured token ceiling was actually exhausted. An empty-content error now reports finish reason, completion-token count, reasoning-token count/presence and attempt count instead of the old ambiguous `no message content` message.

#### T-A4.5 Agent trace / Phoenix debug view

Local JSONL tracing requires no extra package:

```powershell
$env:FINAGENT_AGENT_TRACE = "1"
$env:FINAGENT_AGENT_TRACE_BACKEND = "jsonl"
$env:FINAGENT_AGENT_TRACE_JSONL = ".finagent\a2-agent-trace.jsonl"
```

For Phoenix:

```powershell
python -m pip install -e ".[observability]"
python -m pip install arize-phoenix
phoenix serve
```

Then in the FinAgent terminal:

```powershell
$env:FINAGENT_AGENT_TRACE = "1"
$env:FINAGENT_AGENT_TRACE_BACKEND = "both"
$env:FINAGENT_AGENT_TRACE_OTLP_ENDPOINT = "http://localhost:6006/v1/traces"
$env:FINAGENT_AGENT_TRACE_PROJECT = "finagent-a2"
```

Open `http://localhost:6006`. The trace should expose nested discovery rounds, LLM latency/token counts, provider attempt count, AST/sandbox failures, repair/replacement/checkpoint events, Factor Quant report identities and selected factor digests.

Prompt/generated-code display is opt-in:

```powershell
$env:FINAGENT_AGENT_TRACE_CAPTURE_CONTENT = "1"
```

Do not enable content capture when exporting or sharing traces. Even when enabled, hidden model reasoning is not recorded; only explicit request/response content is eligible for capture.

#### T-A4.6 Focused CI tests

```bash
python -m pytest -q \
  tests/test_local_ashare_data_layer_v126.py \
  tests/test_ashare_freeze_supplemental_v127.py \
  tests/test_ashare_legacy_anomaly_v127.py \
  tests/test_ashare_suspension_session_semantics_v127.py \
  tests/test_ashare_factor_acceptance_a2.py \
  tests/test_ashare_research_correctness_a25.py \
  tests/test_agent_generation_robustness_observability.py
```

Windows:

```powershell
python -m pytest -q `
  tests\test_local_ashare_data_layer_v126.py `
  tests\test_ashare_freeze_supplemental_v127.py `
  tests\test_ashare_legacy_anomaly_v127.py `
  tests\test_ashare_suspension_session_semantics_v127.py `
  tests\test_ashare_factor_acceptance_a2.py `
  tests\test_ashare_research_correctness_a25.py `
  tests\test_agent_generation_robustness_observability.py
```

CI uses synthetic Parquet and fake LLM providers; the real multi-GB/DeepSeek acceptance must still be run locally.


### T-A5 — read-only Research UI acceptance

Install and run the dedicated visualization tests:

```bash
python -m pip install -e ".[dev,visualization]"
python -m pytest -q tests/test_research_visualization.py
```

Windows launch:

```powershell
python scripts/run_research_ui.py `
  --report reports\local_ashare_factor_research_a2p5.json `
  --feature-store .finagent\local-ashare-factor-a2p5\generated_features.sqlite `
  --trace .finagent\a2-agent-trace.jsonl `
  --phoenix-url http://localhost:6006
```

Ubuntu launch:

```bash
python scripts/run_research_ui.py \
  --report reports/local_ashare_factor_research_a2p5.json \
  --feature-store .finagent/local-ashare-factor-a2p5/generated_features.sqlite \
  --trace .finagent/a2-agent-trace.jsonl \
  --phoenix-url http://localhost:6006
```

Open `http://localhost:8501` and verify:

- system completion and research outcome are shown separately;
- candidate denominator count equals development, validation and stability counts;
- denominator drift causes report rejection rather than candidate omission;
- development-versus-validation, rolling/subperiod RankIC and quantile charts preserve signed values;
- HAC, block-bootstrap, Holm and BH evidence is visible for each factor;
- frozen ensemble weights/directions and signed comparison are visible;
- split warm-up, first-session and minimum eligible-asset diagnostics are visible;
- generated feature SQLite is opened in read-only mode and is not modified;
- malformed/orphan JSONL records produce warnings without corrupting valid spans;
- hidden reasoning text is absent while reasoning-token metadata may be shown;
- reserve status and `promotion_eligible=false` remain visible;
- the UI has no LLM call, rerun, prompt-edit, promotion, PAPER or reserve-access action.

Phoenix remains optional. The Research UI must work from immutable report JSON alone. Full usage and governance details are in `docs/guides/research-visualization.md`.


### T-A6 — A2.6/A3/A4 unified acceptance and debug

Run this gate after A4 code changes and before any 2025+ reserve access.

#### T-A6.1 Synchronize and install

Windows:

```powershell
git checkout main
git pull --ff-only
python -m pip install -e ".[dev,local-parquet,visualization]"
```

Ubuntu:

```bash
git checkout main
git pull --ff-only
python -m pip install -e ".[dev,local-parquet,visualization]"
```

#### T-A6.2 Focused regression

Windows:

```powershell
$env:PYTHONUTF8 = "1"
$env:PYTHONNOUSERSITE = "1"
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = "1"

python -m pytest -q `
  tests\test_local_ashare_data_layer_v126.py `
  tests\test_ashare_suspension_session_semantics_v127.py `
  tests\test_ashare_robust_research_a26.py `
  tests\test_ashare_execution_a3.py `
  tests\test_ashare_execution_edge_cases_a3.py `
  tests\test_ashare_portfolio_validation_a4.py
```

Ubuntu:

```bash
PYTHONNOUSERSITE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
python -m pytest -q \
  tests/test_local_ashare_data_layer_v126.py \
  tests/test_ashare_suspension_session_semantics_v127.py \
  tests/test_ashare_robust_research_a26.py \
  tests/test_ashare_execution_a3.py \
  tests/test_ashare_execution_edge_cases_a3.py \
  tests/test_ashare_portfolio_validation_a4.py
```

#### T-A6.3 Real A2.6 source and replay

A4 accepts only a frozen A2.6 report. Run the deterministic or Agent A2.6 protocol first and verify exact replay:

```powershell
python scripts\run_local_ashare_robust_research.py `
  configs\research\local_ashare_robust_research.local.toml `
  --verify-content

python scripts\run_local_ashare_robust_research.py `
  configs\research\local_ashare_robust_research.local.toml `
  --frozen-report reports\local_ashare_robust_research_a26.json `
  --assert-replay `
  --verify-content `
  --report reports\local_ashare_robust_research_a26_replay.json
```

Required source invariants:

```text
schema_version = finagent.ashare-robust-research-program.v1
program_status = frozen
reserve.status = untouched
candidate denominator unchanged
walk-forward/gate/selection identities replay exactly
```

If A2.6 returns `NO_ROBUST_FACTOR_FOUND`, A4 must emit `NO_ROBUST_FACTOR_FAMILY` and must not substitute a weaker factor.

#### T-A6.4 A3 local execution smoke

```powershell
python scripts\run_ashare_execution_smoke.py `
  configs\execution\ashare_execution_smoke.local.toml `
  --verify-content
```

Check normal buy/sell, same-session T+1 rejection, next-session release, board quantity rules, zero buy-side stamp duty, positive configured sell-side stamp duty and non-negative cash. Add targeted local cases for any observed suspension or price-limit date before relying on A4 reason-code attribution.

#### T-A6.5 A4 internal economic validation

```powershell
Copy-Item `
  configs\execution\ashare_portfolio_validation_a4.example.toml `
  configs\execution\ashare_portfolio_validation_a4.local.toml

python scripts\run_ashare_portfolio_validation.py `
  configs\execution\ashare_portfolio_validation_a4.local.toml `
  --verify-content
```

Outputs:

```text
reports/local_ashare_portfolio_validation_a4.json
reports/local_ashare_portfolio_validation_a4_ledger.jsonl
```

The report must expose:

```text
system acceptance separately from economic outcome
source A2.6/factor/plan/universe identities
fold train/test periods
net and gross NAV/return/Sharpe/drawdown
fees, slippage and gross-to-net drag
turnover and target implementation shortfall
order/fill/rejection counts and reason-code attribution
maximum ex-post participation
HAC and circular block-bootstrap evidence
promotion_eligible = false
reserve.status = untouched
```

A4 full-day volume is diagnostic only and must not decide the open fill. Gross and net ledgers must use the same target and A3 tradeability/quantity/cash rules; only explicit fees and slippage differ.

#### T-A6.6 Byte-identical A4 replay

```powershell
python scripts\run_ashare_portfolio_validation.py `
  configs\execution\ashare_portfolio_validation_a4.local.toml `
  --frozen-report reports\local_ashare_portfolio_validation_a4.json `
  --assert-replay `
  --verify-content `
  --report reports\local_ashare_portfolio_validation_a4_replay.json `
  --ledger reports\local_ashare_portfolio_validation_a4_replay_ledger.jsonl
```

Both must match exactly:

```text
portfolio_validation_id
ledger_digest
```

The original and replay JSONL ledgers must be byte-identical. Do not weaken the gate to approximate float equality. Non-deterministic aggregation must be corrected with deterministic ordering/stable summation.

#### T-A6.7 Manual accounting/debug checklist

Inspect at least the first rebalance, one sell after T+1 release, one adjusted/rejected order and each fold boundary:

```text
pretrade NAV = cash + marked positions
fill cash delta = notional +/- fee components
position total = sellable + unsettled
same-session buys are unsettled
next-session inventory is sellable
close NAV uses exact-session close or the last explicit mark only for an existing suspended/missing holding
net NAV never exceeds gross NAV solely because of costs
fees/slippage reconcile to gross-to-net divergence
requested/executable/rejected quantities reconcile
A4 never requests a DatasetRequest covering reserve
```

Record peak memory, runtime, cash-fallback count, rejected-order ratio, maximum participation and the most frequent reason codes. Treat unexpected cash fallback or high rejection as a debugging signal, not automatically as Alpha failure.

#### T-A6.8 Full release gate and visualization

```powershell
python -m pytest -q
ruff check src tests scripts --select E9,F63,F7,F82
mypy src/finagent/data src/finagent/research src/finagent/backtest
python -m build
python -m pip check
```

Use the current Research UI/Phoenix for A2.6 factor/Agent diagnosis. A4 report/NAV/order visualization is a read-only follow-up surface; until then use the A4 JSON and JSONL evidence directly.


### T-A8 — FinAgent Workspace V2 pre-reserve acceptance

Run after any V2 catalog, protocol, A2.6/A4 review, execution-ledger or frontend-cockpit change and before A5 reserve evaluation.

#### T-A8.1 Python/API contract

```bash
python -m pytest -q \
  tests/test_workspace_api_v1.py \
  tests/test_workspace_api_v2.py \
  tests/test_visualization_semantic_contract_v2.py \
  tests/test_visualization_semantic_a2_compat.py \
  tests/test_research_visualization.py \
  tests/test_research_ui_app.py
```

Acceptance:

- V1 compatibility remains green;
- V2 derived SQLite catalog rebuilds without modifying source reports;
- protocol diff is deterministic and excludes outcome fields;
- A2.6 Gate/statistical/fold projections preserve frozen evidence;
- A4 portfolio/economic metrics preserve authoritative values;
- derived rolling/Gate-cell/realized-weight/A3-binding projections are labelled `derived`;
- detailed execution is accepted only from a digest-matched immutable A4 JSONL ledger;
- no fabricated A3 authoritative lineage node is created;
- reserve remains visible and unchanged;
- review bundle contains manifest, lineage, protocol diff, CSV summaries and source evidence;
- POST/PUT/PATCH/DELETE remain absent from V2 product routes.

#### T-A8.2 Frontend

```bash
cd workspace
npm ci
npm run typecheck
npm run test
npm run build
npx playwright install chromium
npm run e2e
cd ..
```

Browser acceptance must show the Research Governance Cockpit, lifecycle, reserve state and V2 portfolio/execution/governance navigation without any promote/rerun/reserve/order control.

#### T-A8.3 Quality

```bash
ruff check \
  src/finagent/visualization/workspace_api.py \
  src/finagent/visualization/workspace_v2.py \
  scripts/run_workspace.py \
  scripts/export_workspace_review_bundle.py \
  tests/test_workspace_api_v1.py \
  tests/test_workspace_api_v2.py \
  --select E4,E7,E9,F
mypy src/finagent/visualization/workspace_api.py src/finagent/visualization/workspace_v2.py
python -m pip check
```

#### T-A8.4 Real-evidence human review

Launch with the exact frozen A2.6/A4 report roots and canonical Agent audit database. Verify one A4 report against its digest-matched ledger: lifecycle IDs, Gate evidence, NAV, fold boundaries, fees, slippage, decisions, fills, reason attribution, target-realized drift, protocol diff and review bundle identities must agree with source artifacts. The 2025+ reserve must still be `untouched` before A5.

### T-A9 — A5-1 ReserveEligibilitySeal acceptance

Run after any reserve-eligibility contract, replay-proof, review-attestation or A5 authority-boundary change. This stage must not access reserve data.

```bash
python -m pytest -q tests/test_ashare_reserve_eligibility_a5.py
python -m compileall -q src/finagent/research/ashare_reserve.py scripts/attest_v2_reserve_review.py scripts/seal_ashare_reserve_eligibility.py
```

Acceptance:

- exact A2.6 frozen identity is bound and `program_status=frozen`;
- A4 source digest/spec/factor family exactly bind the A2.6 reference;
- A2.6 and A4 replay reports match reference evidence modulo `mode`;
- immutable JSONL ledger recomputes to the A4 `ledger_digest`;
- V2 review bundle contains the same A2.6/A4/ledger artifacts;
- every required V2 automated/read-only check is explicitly attested as PASS;
- protocol/ledger/reserve/no-mutation/no-Agent-feedback human confirmations are present;
- authority policy cannot enable feedback, tuning or Agent/UI reserve authority;
- same frozen inputs produce the same `seal_id`;
- append-only store blocks a different seal for the same reserve/program/A4 identity;
- source evidence remains unchanged and seal output says `reserve_consumed=false`;
- no A5-2 runner or reserve data access is reachable from A5-1.

CI should run this test on Windows and Ubuntu. Full project tests remain required before merge.

### T-A10 — A5-2 one-shot runner / terminal evidence acceptance

Run after any A5 execution-protocol, final-training, frozen-policy reuse, reserve-engine or terminal-evidence change. Tests use synthetic/fake reserve engines only; CI must not open production reserve data.

```bash
python -m pytest -q tests/test_ashare_reserve_eligibility_a5.py tests/test_ashare_reserve_runner_a5.py
python -m py_compile src/finagent/research/ashare_reserve.py src/finagent/research/ashare_reserve_runner.py src/finagent/backtest/ashare_reserve.py src/finagent/backtest/ashare_portfolio.py
```

Acceptance:

- only the exact persisted A5-1 seal, exact A2.6/A4 reports and sealed Git identity enter execution;
- final training is half-open and stops at `reserve.start`;
- reserve test interval is exactly the sealed reserve interval;
- reserve calendar materialization occurs once and supplies the terminal fold sessions;
- existing A4 numeric/economic policy is reused without threshold mutation;
- terminal statuses are limited to `RESERVE_PASS` / `RESERVE_FAIL`;
- policy failure and operational failure are legal terminal FAIL outcomes;
- automatic retry after terminal evidence is forbidden/idempotently short-circuited;
- terminal evidence binds dataset, ledger, fold, aggregate, policy, code and eligibility identities;
- `promotion_eligible=false` for both PASS and FAIL;
- the legacy A5-2 terminal schema remains replayable and cannot counterfeit A5-3 durability;
- the A5-3 guarded runner is tested separately before any production reserve execution.

CI runs the A5 contract on Windows and Ubuntu. Full project tests remain required before merge.

### T-A11 — A5-3 consumed-state / crash recovery / replay acceptance

Run after any consumption-state, terminal persistence, crash-recovery or reserve-audit change. All tests use synthetic reserve engines; CI must not access production reserve observations.

```bash
python -m pytest -q tests/test_ashare_reserve_eligibility_a5.py tests/test_ashare_reserve_runner_a5.py tests/test_ashare_reserve_lifecycle_a5.py
python -m py_compile src/finagent/research/ashare_reserve.py src/finagent/research/ashare_reserve_lifecycle.py src/finagent/research/ashare_reserve_runner.py src/finagent/backtest/ashare_reserve.py src/finagent/backtest/ashare_portfolio.py
```

Acceptance:

- a durable `CONSUMED` claim is committed before `engine.evaluate()` is reachable;
- concurrent claim attempts produce exactly one `acquired=true`;
- runtime/report/preflight failure before claim leaves reserve unconsumed;
- claim persistence failure prevents reserve evaluation;
- terminal persistence failure leaves the claim `CONSUMED` and blocks every automatic retry;
- a pre-existing claim without terminal evidence fails closed and requires explicit recovery;
- crash recovery emits terminal `RESERVE_FAIL` without reserve re-access;
- completed terminal evidence persists and replays its canonical ledger artifact;
- terminal-without-audit is reconciled without another engine evaluation;
- ledger tampering is detected by replay audit;
- reopening all SQLite stores preserves exact claim/terminal/audit identities;
- terminal v2 binds the durable claim and reports `DURABLE_PRE_ACCESS_V1`;
- PASS and FAIL remain non-promotional and automatic retry remains forbidden.

A5-3 acceptance makes the one-shot state primitive production-capable, but CI still must not execute the real reserve. Actual reserve consumption requires the reviewed production seal and human authorization.

## 4. Interpretation boundary

The A-share evidence layers have different meanings:

```text
A2/A2.6  factor-level statistical and stability evidence
A3       target-to-executable-order rule plumbing
A4       internal walk-forward portfolio economic evidence
```

A4 models T+1, board quantity rules, suspension/price-limit constraints, configured fees and slippage, but it remains an internal 2018–2024 protocol. It does not certify a survivorship-free universe, order-book queue, market impact, realtime operation or future persistence.

Do not send a result to promotion or PAPER merely because `system_acceptance.passed` is true. A4 must pass its separate economic gate, all identities/replay must be frozen, and the 2025+ reserve must remain untouched until the one-shot reserve protocol is explicitly authorized.

## 5. Failure severity

P0 — block the next milestone:

- PIT/look-ahead or split leakage;
- frozen identity mismatch;
- wrong units/timezone/timestamp semantics;
- suspension placeholder treated as tradable;
- forward horizon stretched across suspension;
- candidate denominator, direction or weight mutation;
- validation evidence entering Agent feedback;
- reserve access;
- replay failure;
- accepted generated code bypassing AST/sandbox guardrails;
- stale candidate checkpoint reused after scope change;
- `+/-inf` in accepted evidence.

P1 — record and continue when bounded:

- incomplete supplemental status coverage;
- candidate-only, non-survivorship-certified universe;
- bounded provider transient/retry;
- generated candidate requiring conformance repair/replacement;
- large-panel performance limits.

P2 — deployment hardening:

- cryptographic/physical evidence isolation;
- production realtime feeds and broker connectivity;
- centralized multi-user observability/evaluation infrastructure;
- high-availability reconciliation infrastructure.
