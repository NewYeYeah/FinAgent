from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


SECTION = r'''
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

'''


def main() -> None:
    path = ROOT / "docs/testing/testing.md"
    text = path.read_text(encoding="utf-8")
    anchor = "## 4. Interpretation boundary\n"
    if anchor not in text:
        raise RuntimeError("testing guide interpretation anchor is absent")
    if "### T-A6 — A2.6/A3/A4 unified acceptance and debug" not in text:
        text = text.replace(anchor, SECTION + anchor, 1)
    old = '''A2 validates factor-level evidence:\n\n```text\nIC / RankIC / ICIR\nhorizon decay\nquantile monotonicity and spread\nturnover proxy\ncoverage\nfactor-value redundancy\nfrozen multi-factor ensemble\nindependent validation and replay\n```\n\nIt does not certify portfolio execution returns because A-share T+1, lot size, price limits, asymmetric fees and minimum commissions are not yet modeled in the A2 path.\n\nDo not send A2 results to sealed holdout, promotion or PAPER. A-share execution semantics are the next gate.\n'''
    new = '''The A-share evidence layers have different meanings:\n\n```text\nA2/A2.6  factor-level statistical and stability evidence\nA3       target-to-executable-order rule plumbing\nA4       internal walk-forward portfolio economic evidence\n```\n\nA4 models T+1, board quantity rules, suspension/price-limit constraints, configured fees and slippage, but it remains an internal 2018–2024 protocol. It does not certify a survivorship-free universe, order-book queue, market impact, realtime operation or future persistence.\n\nDo not send a result to promotion or PAPER merely because `system_acceptance.passed` is true. A4 must pass its separate economic gate, all identities/replay must be frozen, and the 2025+ reserve must remain untouched until the one-shot reserve protocol is explicitly authorized.\n'''
    if old in text:
        text = text.replace(old, new, 1)
    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
