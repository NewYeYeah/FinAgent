# MT5 continuous-market smoke and deferred US-I0 acceptance

This guide separates two different purposes that must not be conflated:

```text
continuous/near-continuous MT5 instruments
        -> engineering smoke only

U.S. equity candidates during active quote publication
        -> US-I0 / US-D3 formal local evidence
```

The continuous-market smoke exists so realtime read-only development can continue while U.S. equity quote freshness is temporarily unavailable. It cannot replace the final 20-30 name EngineeringUniverse, the accepted U.S. quote snapshot, MT5-D0 reconciliation or US-D3 certification.

## 1. Continuous-market engineering smoke

Default symbols are:

```text
EURUSD
GBPUSD
USDJPY
```

These are used because the current MetaQuotes-Demo connection has demonstrated continuously updating weekday quotes and a stable broker-clock offset. They are not members of the U.S. research universe and are not used as substitute U.S. assets.

Run:

```powershell
conda activate finagent
cd D:\PythonWorkspace\FinAgent

python scripts\smoke_mt5_continuous_quotes.py `
  --symbols EURUSD GBPUSD USDJPY `
  --reference-symbols EURUSD GBPUSD USDJPY `
  --minimum-symbol-count 3 `
  --maximum-quote-age-seconds 60 `
  --maximum-future-quote-skew-seconds 5 `
  --expected-package-version 5.0.6147 `
  --output reports\mt5\mt5_continuous_quote_smoke.json
```

Expected engineering result while those markets are actively quoting:

```text
passed = true
passed_symbol_count = 3
clock_evidence.passed = true
stage_exit_authority = false
research_universe_authority = false
execution_authority = false
```

The smoke validates:

- read-only `symbol_info` / `symbol_info_tick` retrieval;
- broker-server identity;
- evidence-bound broker-clock normalization;
- normalized quote freshness;
- positive bid/ask and diagnostic spread calculation;
- explicit visible/tradable state;
- fail-closed stale/future/missing-tick behavior.

It deliberately does not call `symbol_select`, `order_check`, `order_send` or any account/position mutation API.

## 2. Deferred US-I0 operator acceptance

The first real post-fix U.S. quote report established that broker-clock normalization works, but formal US-I0 remains pending because:

```text
36 / 40 candidate symbols -> not_visible
4 / 40 seed symbols       -> stale_quote at the observed off-session time
```

This is a deferred operator task, not an implementation blocker for preimplementation work.

Deferred task:

1. manually expose the intended 40 U.S. candidate symbols in MT5 Market Watch;
2. rerun `probe_us_i0_candidate_quotes.py` while U.S. equity quotes are actively updating;
3. immediately rerun the fresh MT5 inventory probe;
4. rerun the v3 final EngineeringUniverse finalizer;
5. review seed retention and the frozen 50 bps spread gate;
6. only then continue MT5-D0 reconciliation and formal US-D3 certification.

No continuous-market smoke report may be supplied to the US-I0 finalizer or US-D3 certifier.

## 3. US-B0 preimplementation while US-D3 is pending

The formal baseline runner remains fail-closed until `docs/status.toml` actually advances to `US-B0`. Development can nevertheless continue on contracts and synthetic/fixture regressions.

The pilot walk-forward design is frozen before formal result inspection as three expanding folds:

```text
Fold 1
train       [2026-01-02, 2026-02-02)
validation  [2026-02-02, 2026-02-17)
evaluation  [2026-02-17, 2026-03-02)

Fold 2
train       [2026-01-02, 2026-02-17)
validation  [2026-02-17, 2026-03-02)
evaluation  [2026-03-02, 2026-03-16)

Fold 3
train       [2026-01-02, 2026-03-02)
validation  [2026-03-02, 2026-03-16)
evaluation  [2026-03-16, 2026-03-30)
```

All boundaries are timezone-aware UTC day boundaries. Actual observations remain filtered by the accepted XNYS regular-session calendar, so DST/open-close changes are not hard-coded into the split itself.

Freeze the deterministic protocol artifact with:

```powershell
python scripts\freeze_us_b0_pilot_walkforward.py `
  --output reports\us_b0\us_b0_pilot_walkforward_protocol.json
```

This artifact has no factor-selection or Alpha authority. After formal US-D3 acceptance, each fold's evaluation window is bound to the accepted `USBaselineRunSpec` through a content-addressed `USBaselineFoldExecutionSpec` before real materialization begins.

## Authority boundary

Until the deferred U.S. equity task is completed:

```text
current project stage          US-D3
formal US-I0 final universe    pending
formal US-D3 certification     pending
continuous MT5 smoke           engineering-only
US-B0 walk-forward protocol    preregistered preimplementation
US-B0 real-data evidence       forbidden until stage authority advances
```

This separation allows implementation to continue without converting convenience test data into research authority.
