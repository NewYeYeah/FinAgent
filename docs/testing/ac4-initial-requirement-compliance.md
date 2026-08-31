# A-C4 Initial Requirement Compliance Acceptance

A-C4 is a read-only repository compliance audit. It classifies the frozen Historical v1.0 requirement denominator as `PASS`, `PARTIAL`, `DEFERRED` or `N/A` and binds every classification to repository implementation/test references.

It does **not** run research, consume the A-share production reserve, promote a strategy, start PAPER, contact a broker or grant live-capital authority.

## Focused gate

Ubuntu / Python 3.11:

```bash
PYTHONNOUSERSITE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
python -m pytest -q tests/test_initial_requirement_compliance_ac4.py

python -m py_compile \
  src/finagent/runtime/initial_requirement_compliance.py \
  scripts/run_initial_requirement_compliance_audit.py

ruff check \
  src/finagent/runtime/initial_requirement_compliance.py \
  scripts/run_initial_requirement_compliance_audit.py \
  tests/test_initial_requirement_compliance_ac4.py \
  --select E4,E7,E9,F

mypy --follow-imports=silent \
  src/finagent/runtime/initial_requirement_compliance.py
```

Windows PowerShell compatibility smoke:

```powershell
$env:PYTHONUTF8 = "1"
$env:PYTHONNOUSERSITE = "1"
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = "1"
python -m pytest -q tests\test_initial_requirement_compliance_ac4.py
```

## Generate the audit

```powershell
python scripts\run_initial_requirement_compliance_audit.py `
  configs\acceptance\ashare_initial_requirement_compliance_ac4.toml
```

Outputs:

```text
reports/ashare_initial_requirement_compliance_ac4.json
reports/ashare_initial_requirement_compliance_ac4.md
```

Required result for A-C4 closure:

```text
audit_complete = true
historical_freeze_ready = true
PARTIAL = 0
production_reserve_authority = false
reserve_accessed_by_audit = false
```

The frozen v1 denominator contains 22 requirements. The accepted initial classification is:

```text
PASS     = 15
DEFERRED = 7
PARTIAL  = 0
N/A      = 0
```

`DEFERRED` is not a failed test. It is reserved for capabilities intentionally moved out of A-share Historical v1.0 by the v4.0 strategy, including authoritative benchmark evidence, explicit corporate-action events, capacity/impact, advanced risk attribution, A-share PAPER deployment, provider-neutral realtime and QMT.

## Invariants

- the 22 requirement IDs are a frozen denominator; removal or silent replacement fails closed;
- every `PASS` entry must reference both implementation and test/evidence files;
- every repository reference must resolve inside the checked-out repository;
- changing any classification or reference changes the manifest SHA and therefore the `audit_id`;
- the generated report binds the exact Git SHA and manifest SHA-256;
- the audit never infers a missing capability from adjacent code;
- A5 one-shot infrastructure may be `PASS` while real production reserve execution remains separately human-authorized and outside Historical v1.0 closure.

A-C5 should consume the generated A-C4 `audit_id` and exact merged-main Git SHA as freeze inputs rather than copying the Markdown table by hand.
