# A-C5 — A-share Historical v1.0 Freeze

Status: **Implementation complete / real local freeze must be executed after merge**

A-C5 freezes the accepted A-share historical product without introducing another research, portfolio, execution or operational authority.

## Release identity

The release name is fixed as:

```text
FinAgent A-share Historical v1.0
```

The canonical runtime is:

```text
src/finagent/runtime/ashare_historical_v1_freeze.py
```

The CLI is:

```text
scripts/freeze_ashare_historical_v1.py
```

The default configuration is:

```text
configs/acceptance/ashare_historical_v1_freeze.example.toml
```

Default outputs are:

```text
reports/finagent_ashare_historical_v1_freeze.json
reports/finagent_ashare_historical_v1_freeze.md
reports/finagent_ashare_historical_v1_freeze.zip
```

## Required evidence

A real freeze requires:

```text
accepted real A-C3 report
+ content-hashed frozen A-share dataset manifest
+ exact replayable A-C4 audit
+ final merged release Git SHA
+ unchanged historical financial/research core since A-C3
```

A-C3 may be either:

```text
POPULATED_STRATEGY
```

or the reviewed terminal research outcome:

```text
NO_ROBUST_FACTOR_FAMILY
```

The no-alpha path remains a valid v1.0 result. A-C5 does not fabricate a strategy, MarketBarSeries or portfolio result merely to make the release look populated.

## Git/evidence drift rule

A-C3 evidence may have been produced by an ancestor of the final A-C5 release revision because A-C4/A-C5 themselves are additive audit/release stages. However, A-C5 runs a Git diff over the accepted historical financial/research product paths and rejects the freeze if those paths changed after the A-C3 evidence revision.

A-C4 is different: for a real freeze it must be regenerated on the exact final release Git SHA. This ensures the compliance matrix describes the code being released rather than an earlier checkout.

## Evidence replay and artifact verification

A-C5:

- recomputes the existing A-C3 `acceptance_id` from its frozen identities/checks;
- verifies every A-C3 artifact SHA-256 and byte size recorded by A-C3;
- requires a successful data-certification CommandRun and freezes its CommandRun identity plus certification-report SHA-256/byte size; existing optional `evidence_ids` are preserved but are not fabricated or required;
- validates the frozen dataset manifest through `LocalAshareFrozenManifest` and requires `content_hashed=true`;
- exactly replays A-C4 from its frozen TOML manifest and requires `PARTIAL=0`;
- freezes the seven strategic deferred capabilities accepted by A-C4;
- binds repository dependency/environment files by content digest;
- writes deterministic JSON/Markdown release records and a deterministic ZIP package.

The ZIP uses fixed member timestamps and sorted archive paths so the same frozen inputs produce the same package SHA-256.

## Environment identity boundary

A-C5 binds:

```text
pyproject.toml
environment/environment.yml
environment/requirements.txt
environment/requirements-dev.txt
workspace/package-lock.json
```

The frontend package lock is a resolved dependency lock. The Python files are declarative dependency/environment surfaces, not a claim that a fully resolved Python lock file exists.

## Deferred capabilities

Historical v1.0 freezes the A-C4 deferred set unchanged:

```text
advanced_risk
benchmark_evidence
capacity_impact
corporate_actions
internal_paper
qmt
realtime_gateway
```

These are explicit follow-up capabilities, not failed Historical v1.0 requirements.

## Reserve / operational boundary

A-C5 writes release files only. It does not consume the production reserve and does not imply strategy promotion, PAPER deployment, broker connectivity or live-capital authority.

## CI semantics

CI uses `ci_contract_fixture` and may prove:

```text
contract_valid = true
frozen = false
```

Synthetic CI evidence can never produce a real Historical v1.0 freeze. Only `real_local_evidence` with accepted A-C3 evidence may set:

```text
contract_valid = true
frozen = true
```

Focused acceptance is documented in `docs/testing/ac5-historical-v1-freeze.md`.

## Post-merge real freeze

After this A-C5 implementation is merged:

1. checkout/pull exact `main`;
2. regenerate A-C4 on that exact Git SHA;
3. keep the already accepted A-C3 report only if its Git SHA is an ancestor and A-C5 reports zero historical-core drift;
4. run `scripts/freeze_ashare_historical_v1.py` in `real_local_evidence` mode;
5. retain the JSON/Markdown/ZIP outputs and package SHA-256 as the Historical v1.0 release evidence.

If the old A-C3 report binds a revision before a later historical-core correction, A-C5 deliberately fails closed and A-C3 must be rerun on the corrected core rather than laundering old evidence into the release.
