# A-C5 A-share Historical v1.0 Freeze Acceptance

A-C5 is a release identity/freeze stage. It must not rerun alpha research, consume reserve observations, promote a strategy, start PAPER, contact a broker or authorize live capital.

## Focused CI gate

Ubuntu / Python 3.11:

```bash
PYTHONNOUSERSITE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
python -m pytest -q tests/test_ashare_historical_v1_freeze_ac5.py

python -m py_compile \
  src/finagent/runtime/ashare_historical_v1_freeze.py \
  scripts/freeze_ashare_historical_v1.py

ruff check \
  src/finagent/runtime/ashare_historical_v1_freeze.py \
  scripts/freeze_ashare_historical_v1.py \
  tests/test_ashare_historical_v1_freeze_ac5.py \
  --select E4,E7,E9,F

mypy --follow-imports=silent \
  src/finagent/runtime/ashare_historical_v1_freeze.py
```

CI fixtures must end with:

```text
contract_valid = true
frozen = false
```

Both fixture paths are tested:

```text
POPULATED_STRATEGY
NO_ROBUST_FACTOR_FAMILY
```

Synthetic/fake evidence must never produce `frozen=true`.

## Final local freeze sequence

Run only after the A-C5 implementation is merged to `main`.

Windows PowerShell:

```powershell
git checkout main
git pull --ff-only

git rev-parse HEAD

python scripts\run_initial_requirement_compliance_audit.py `
  configs\acceptance\ashare_initial_requirement_compliance_ac4.toml

python scripts\freeze_ashare_historical_v1.py `
  configs\acceptance\ashare_historical_v1_freeze.example.toml
```

The A-C4 command is intentionally rerun after the final merge. In real A-C5 mode, the `git_sha` inside the A-C4 report must equal the exact current release SHA.

The existing A-C3 report may be reused only when:

```text
contract_valid = true
accepted = true
real_dataset_attested = true
mode = real_local_dataset
```

and its Git SHA is an ancestor of the release SHA with zero changes in the protected historical financial/research core paths.

If A-C5 reports historical-core drift, do not weaken the check. Rerun A-C3 using the corrected historical core/release lineage.

## Required final result

A real release closes only with:

```text
schema_version = finagent.ashare-historical-v1-freeze.v1
stage = A-C5
contract_valid = true
frozen = true
```

The JSON report must bind:

```text
release Git SHA
A-C3 acceptance_id and evidence Git SHA
A-C3 research outcome
A-C3 program/A4/Strategy/Factor/MarketBar identities
A-C3 data-certification CommandRun identity + certification artifact SHA-256/size
optional existing certification evidence_ids without inventing one
A-C4 audit_id
content-hashed dataset manifest identity
A-C3 artifact digests
repository environment/dependency file digests
seven deferred capability IDs
production-reserve non-consumption boundary
```

For the reviewed no-alpha terminal path, this is valid:

```text
research_outcome = NO_ROBUST_FACTOR_FAMILY
market_bar_series_id = null
```

A-C5 must not create a replacement strategy or MarketBarSeries.

## Freeze artifacts

Default outputs:

```text
reports/finagent_ashare_historical_v1_freeze.json
reports/finagent_ashare_historical_v1_freeze.md
reports/finagent_ashare_historical_v1_freeze.zip
```

Keep the CLI-reported ZIP SHA-256 with the release record.

The ZIP contains the canonical freeze JSON/Markdown, A-C3/A-C4 records, frozen dataset manifest, verified A-C3 evidence artifacts/review bundle and dependency/environment identity files. It does not contain the multi-GB local A-share Parquet corpus.

## Fail-closed conditions

A-C5 must reject at least:

- A-C3 `contract_valid=false`;
- CI/synthetic A-C3 used in real mode;
- A-C3 `accepted=false` or `real_dataset_attested=false` in real mode;
- tampered A-C3 `acceptance_id`;
- changed A-C3 artifact SHA/size;
- missing or unsuccessful data-certification CommandRun;
- missing certification report artifact/output path when it is not already recorded in A-C3 artifacts;
- non-content-hashed or wrong-version dataset manifest;
- A-C3 Git SHA not ancestral to release SHA;
- protected historical-core changes after A-C3;
- A-C4 report not exactly replayable from the frozen compliance manifest;
- A-C4 `PARTIAL > 0`;
- A-C4 deferred set drift;
- A-C4 Git SHA different from the final release SHA in real mode;
- tracked source changes in the local worktree during a real freeze.

## Interpretation boundary

A-C5 freezes what Historical v1.0 actually proved. It does not upgrade the meaning of A2.6/A3/A4 evidence and does not imply persistent alpha, external PAPER readiness, realtime correctness or live-capital suitability.
