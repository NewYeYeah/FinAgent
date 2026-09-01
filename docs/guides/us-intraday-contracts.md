# U.S. intraday core contracts

US-C0 freezes provider-neutral semantics before the U.S. minute Data Plane, resampling, labels or broker mapping are allowed to grow provider-specific rules.

## Contract boundary

```text
TradingCalendarEvidence
LabelSpec
CorporateActionEvent
MarketDataQuery → MarketDataView
AdapterCapabilities
```

These contracts do not create Alpha, execution, PAPER or broker authority.

## TradingCalendarEvidence

`TradingCalendarEvidence` binds a materialized schedule to:

```text
market_id
timezone
source
source_revision
regular_session_minutes
all materialized TradingSession rows
```

`calendar_id` hashes the complete materialized schedule rather than trusting a mutable calendar-library name. `TradingSession` requires timezone-aware open/close timestamps and validates the session date in the calendar timezone. Half-days are explicit and must agree with the observed regular-session duration.

US-C0 contract regression includes known XNYS DST, holiday-absence and half-day fixtures. These fixtures freeze semantics only; they are not themselves the authoritative 1992–2026 XNYS schedule.

## Exact XNYS calendar materialization

The authoritative local schedule is generated once from an exact `exchange_calendars` package version and persisted as JSON evidence. `exchange_calendars` is an operator/materialization dependency, not a FinAgent core runtime dependency.

Current materialization specification:

```text
calendar: XNYS
timezone: America/New_York
start: 1992-01-01
end: 2026-03-31
package: exchange_calendars
exact version: 4.13.2
side: left
```

The requested range is explicit because calendar libraries may otherwise use a moving/default construction window. The persisted evidence records every materialized session, package version, materialization spec, anchor checks and deterministic `calendar_id`.

From the Windows workstation, use the active Conda environment:

```powershell
conda activate finagent
cd D:\PythonWorkspace\FinAgent
python -m pip install "exchange-calendars==4.13.2"

python scripts\materialize_xnys_calendar.py `
  --start 1992-01-01 `
  --end 2026-03-31 `
  --expected-version 4.13.2 `
  --output reports\us_calendar\xnys_1992_2026.json
```

The command fails closed if the installed package version differs from the requested exact version. It also validates high-information NYSE anchors that lie inside the admitted minute-data interval:

```text
2025-07-04            Independence Day closure
2025-11-28            09:30–13:00 ET post-Thanksgiving half-day
2026-03-06            pre-DST 09:30–16:00 ET = 14:30–21:00 UTC
2026-03-09            post-DST 09:30–16:00 ET = 13:30–20:00 UTC
```

The output must report:

```text
passed = true
coverage_boundary_passed = true
observed_package_version = 4.13.2
all anchor_checks passed
calendar_id = trading-calendar-...
```

Only then may `trading_calendar_evidence=true` and `contracts_frozen=true` be recorded in `docs/status.toml`.

## LabelSpec

`LabelSpec` separates label identity from historical `LabelHorizonPolicy` compatibility primitives. Its identity includes:

```text
metric
horizon
horizon_unit
allow_cross_session
price_basis
availability_policy
```

The first intended intraday research label is approximately:

```text
metric = simple_return
horizon = 60
horizon_unit = trading_minutes
allow_cross_session = false
availability_policy = available_at
```

The exact research price basis is chosen by the research protocol. A 60-trading-minute label is therefore not identity-equivalent to four 15-minute bars or a one-day label.

## CorporateActionEvent

`CorporateActionEvent` is market/research evidence and is deliberately distinct from `operations.domain.CorporateAction`, which mutates an account/portfolio state.

Supported initial evidence types are:

```text
split
cash_dividend
cash_event
```

Split events expose only the mechanically supportable split price factor (`1 / split_ratio`). Cash events do not fabricate a multiplicative total-return adjustment without reference-price and policy evidence. `available_at` remains explicit so later research cannot use corporate-action knowledge before it was available.

## MarketDataQuery / MarketDataView

`MarketDataQuery` is always bounded:

```text
market_id
assets
[start, end)
interval
fields
session_policy
adjustment_policy
availability_policy
```

Both assets and value fields must be non-empty. Start/end are timezone-aware and the time window is explicitly half-open: start inclusive, end exclusive.

`MarketDataView` is an identity-bound lazy descriptor. US-C0 forbids treating the query contract as permission to materialize an unbounded dense panel.

## AdapterCapabilities

`AdapterCapabilities` records what one FinAgent adapter actually implements and tests. It is separate from `data.ingestion.ProviderCapabilities`, which describes a provider/API surface.

For example:

```text
provider says historical_minute = true
provider says corporate_actions = true

FinAgent adapter may still support only:
  interval = 1m
  adjustment = raw
  corporate actions = false
```

The adapter must reject a split-adjusted query until that functionality exists in the adapter. Provider claims are never inherited automatically.

## Current US-C0 boundary

The five contracts and materialization tooling are implemented. The remaining US-C0 blocker is the real local XNYS materialization report. Until that evidence exists, `docs/status.toml` keeps `contracts_frozen=false` and `trading_calendar_evidence=false`.
