# Visualization V3-3 Changelog

## Typed deep-link contract

V3-3 adds the read-only `WorkbenchReference` projection for verified navigation across:

```text
AgentRun
Evidence / Artifact
Factor
ResearchProgram
A4 PortfolioValidation
A5 Reserve lifecycle
ConfigSnapshot / ConfigDiff
CommandRun
```

Resolution is fail-closed. Canonical root evidence is preferred over an external reference with the same identity; ambiguous non-root identities are rejected rather than guessed.

## Artifact Inspector

- Generated-feature artifacts are verified metadata identities keyed by the canonical feature digest.
- Source-report artifacts are registered from immutable Evidence source identities.
- The browser supplies only `artifact_id`; arbitrary host paths are not accepted.
- Text preview is allowed only when the registered source resolves inside a configured report root.
- Preview size is bounded server-side; unsupported/binary/unavailable sources remain explicit states.

## Command / configuration links

- The Evidence Plane can optionally open the V3-2 durable CommandRun SQLite store with `mode=ro` and `query_only`.
- ConfigSnapshot can link to deterministic ConfigDiff identities and bound CommandRuns.
- CommandRun can link to a bound ConfigSnapshot and produced Evidence when that Evidence is present in the configured immutable catalog.
- Persisted command artifact host paths remain display-only on the Control Plane and are never converted into browser-navigable file paths.

## API

Additive GET-only routes:

```text
GET /api/v3/deep-links/status
GET /api/v3/refs/{kind}/{identity}
GET /api/v3/artifacts/{artifact_id}
GET /api/v3/command-runs
GET /api/v3/command-runs/{command_run_id}
```

`run_workspace.py` accepts optional `--command-store`; if the default durable command store does not exist, the Evidence Plane remains usable without it.

## Workbench

- Agent verified evidence/factor identifiers route through typed references while unknown audit strings remain unresolved text.
- Reference Inspector preserves `WorkbenchContext` when navigating related identities.
- ConfigSnapshot and ConfigDiff identities are directly inspectable.
- CommandRun Inspector links to typed CommandRun, ConfigSnapshot and produced Evidence identities.
- Hidden reasoning remains `not_persisted_not_projected`; Phoenix/OTLP remains diagnostic-only.

## Acceptance

V3-3 adds backend tests for read-only SQLite access, canonical root preference, cross-object relationships, artifact root confinement, malicious path rejection and GET-only semantics; frontend tests cover typed reference rendering and context-preserving links. The existing Ubuntu/Windows Workspace API matrix is retained.
