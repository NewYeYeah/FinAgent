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
