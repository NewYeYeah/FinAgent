# A-share Execution-aware Portfolio Validation

A4 connects a frozen A2.6 robust factor family to the A3 A-share execution model. It answers whether internally stable factor evidence can survive portfolio construction, T+1, lot rules, suspension/price-limit constraints, fees and slippage.

A4 remains an **internal walk-forward validation**. It does not consume the 2025+ reserve and cannot promote a model.

## 1. Pipeline

```text
Frozen A2.6 ResearchProgram report
        ↓
Frozen factor digests / weights / directions
        ↓
Train-only factor calibration per expanding fold
        ↓
Historical OAS risk forecast
        ↓
Mean-variance PortfolioTarget
        ↓
A3 order compiler and simulated exchange
        ↓
T+1 / board quantity rules / suspension / price limits
        ↓
Gross and net account ledgers
        ↓
Close-to-close NAV and economic evidence
```

A2.6 output `NO_ROBUST_FACTOR_FOUND` is a valid input. In that case A4 writes an explicit `NO_ROBUST_FACTOR_FAMILY` result and does not backtest a replacement factor.

## 2. Timing and reserve boundary

For every A2.6 internal walk-forward fold:

1. factor calibration uses only the fold training range;
2. the target is formed immediately before the exact next-session open;
3. A3 executes at that session open;
4. the account is marked using the exact same-session close;
5. the next target may use information available through the preceding completed session.

`LocalAshareInferenceDataAdapter` reads no forward rows and emits structural all-NaN labels. It is used for test calendars and PIT universe policy reconstruction. The final 2024 test session therefore does not require the first 2025 reserve row.

The ordinary research adapter remains responsible for historical feature windows and train labels. A4 never constructs a `DatasetRequest` covering the reserve.

## 3. Frozen alpha family

`AshareFrozenGeneratedFeatureAlphaModel` receives the exact A2.6:

```text
feature digests
weights
directions
```

Each component is sandboxed, cross-sectionally winsorized and standardized. The frozen weighted score is calibrated to the configured forward-return label using fold-training observations only.

The calibration slope is constrained to be non-negative. A4 therefore cannot silently reverse an A2.6 factor direction after observing an internal test fold.

## 4. Portfolio construction

A4 currently uses:

- `HistoricalRiskForecastBuilder` with OAS covariance;
- `MeanVarianceOptimizer`;
- a configurable active-asset count;
- long-only maximum weights and target cash;
- optional optimizer turnover penalty;
- a cash fallback when a session lacks enough usable assets or risk history.

The portfolio target is not the executed portfolio. A3 subsequently applies cash, T+1, quantity and tradeability rules.

## 5. Gross and net ledgers

A4 runs two synchronized account paths:

### Net ledger

Uses the configured:

```text
broker commission
minimum commission
sell-side stamp duty
transfer fee
optional handling/regulatory fees
slippage
```

### Gross ledger

Uses the same:

```text
signals
targets
T+1
lot rules
suspension and price-limit rules
cash constraint
```

but zero fees and zero slippage.

The difference isolates explicit trading-friction drag. It does not represent an unconstrained theoretical factor portfolio.

## 6. Evidence

The JSON report contains:

```text
net/gross total and annualized return
net/gross volatility and Sharpe
maximum drawdown
gross-to-net return drag
fees and slippage
one-way and gross traded weight
implementation shortfall
order/fill/rejection counts
reason-code attribution
maximum ex-post participation
positive-fold ratio and worst-fold Sharpe
Newey-West/HAC mean-return evidence
circular block-bootstrap evidence
```

The execution ledger is written separately as JSONL and includes every target, compilation decision, fill, fee, inventory state and close mark. Its digest is bound into the report.

Full-day volume is used only for **ex-post participation diagnostics**. It does not decide whether an open order fills.

## 7. Install and configure

```powershell
python -m pip install -e ".[dev,local-parquet]"

Copy-Item `
  configs\execution\ashare_portfolio_validation_a4.example.toml `
  configs\execution\ashare_portfolio_validation_a4.local.toml
```

Set the local paths:

```toml
a2p6_report = "reports/local_ashare_robust_research_a26.json"
feature_store = ".finagent/local-ashare-robust-a26/generated_features.sqlite"
root = "D:/Data/A-Share"
frozen_manifest = "data/manifests/local_ashare_daily.json"
```

Do not point A4 at an A2/A2.5 report. The input must use schema:

```text
finagent.ashare-robust-research-program.v1
```

and must report:

```text
program_status = frozen
reserve.status = untouched
```

## 8. Run

Windows:

```powershell
python scripts\run_ashare_portfolio_validation.py `
  configs\execution\ashare_portfolio_validation_a4.local.toml `
  --verify-content
```

Ubuntu:

```bash
python scripts/run_ashare_portfolio_validation.py \
  configs/execution/ashare_portfolio_validation_a4.local.toml \
  --verify-content
```

Outputs:

```text
reports/local_ashare_portfolio_validation_a4.json
reports/local_ashare_portfolio_validation_a4_ledger.jsonl
```

## 9. Exact replay

```powershell
python scripts\run_ashare_portfolio_validation.py `
  configs\execution\ashare_portfolio_validation_a4.local.toml `
  --frozen-report reports\local_ashare_portfolio_validation_a4.json `
  --assert-replay `
  --verify-content `
  --report reports\local_ashare_portfolio_validation_a4_replay.json `
  --ledger reports\local_ashare_portfolio_validation_a4_replay_ledger.jsonl
```

Replay must reproduce both:

```text
portfolio_validation_id
ledger_digest
```

and the JSONL ledger must be byte-identical.

## 10. Interpretation

A4 separates workflow completion from economic validation:

```text
system_acceptance.passed
research_outcome.execution_validation_passed
```

A completed run can legitimately fail the pre-registered economic gate. Even a passed internal result remains:

```text
promotion_eligible = false
reserve.status = untouched
```

The result only shows performance inside the previously frozen 2018–2024 internal walk-forward domain.

## 11. Current limitations

A4 is intentionally conservative and daily-bar based:

- no order-book queue or intra-day limit-board reopening model;
- no market-impact fill model beyond configured slippage;
- capacity uses ex-post full-day volume diagnostics only;
- no benchmark/sector/style neutral portfolio constraint yet;
- candidate universe is not certified survivorship-free;
- supplemental delisting/ST/suspension history remains partial;
- fees are configuration inputs, not a claim that one schedule applies to every account and year;
- corporate-action cash flows are represented through the existing adjusted research price and raw execution-price contracts, not a full event-ledger treatment.

These limits must remain visible when interpreting A4 returns.
