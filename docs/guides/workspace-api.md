# Workspace API Contract

The V1 API is a read-only projection over immutable FinAgent evidence. The primary usage guide is `docs/guides/workspace.md`; this page records the stable endpoint contract for client development.

```text
GET /api/v1/health
GET /api/v1/catalog
GET /api/v1/evidence/{evidence_id}
GET /api/v1/programs
GET /api/v1/programs/{program_id}
GET /api/v1/portfolio-validations
GET /api/v1/portfolio-validations/{validation_id}
GET /api/v1/factors/{feature_digest}
GET /api/v1/lineage/{evidence_id}
GET /api/v1/widgets
GET /api/v1/agent/runs
GET /api/v1/agent/runs/{run_id}
```

## Contract rules

- responses use the V0 `EvidenceBundle`, `AgentRunProjection` and `FinWidgetSpec` semantics;
- report paths are configured only at process start and are never accepted from a request;
- unsupported schemas fail closed;
- duplicate replay-equivalent identities are deduplicated;
- conflicting payloads claiming one identity are omitted and reported as warnings;
- Agent audit SQLite is opened read-only/query-only;
- product APIs expose no POST/PUT/PATCH/DELETE operation;
- browser-derived presentation series are not returned as authoritative API evidence;
- reserve and promotion state remain visible but cannot be changed.

OpenAPI documentation is available from a running service at `/docs`.


## V2 review endpoints

Visualization V2 retains all V1 GET routes and adds:

```text
GET /api/v2/catalog
GET /api/v2/projects
GET /api/v2/programs/{program_id}/cockpit
GET /api/v2/programs/{program_id}/gates
GET /api/v2/programs/{program_id}/statistics
GET /api/v2/a4/{validation_id}/cockpit
GET /api/v2/a4/{validation_id}/execution
GET /api/v2/governance/{evidence_id}
GET /api/v2/protocol-diff?left=...&right=...
GET /api/v2/evidence/{evidence_id}/raw
GET /api/v2/a4/{validation_id}/review-bundle
```

V2 catalog/protocol/rolling/realized-weight/A3-binding projections are explicitly review/derived surfaces. The server accepts detailed execution lifecycle data only from an immutable JSONL ledger whose canonical digest matches the A4 report.
