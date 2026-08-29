# Visualization V3-4 Changelog

## Stable product SSE

V3-4 adds Server-Sent Events over two normalized Workbench product projections:

```text
AgentActiveRunProjection
CommandRunStreamProjection
```

The stream is a notification/projection transport. Canonical Agent audit, immutable Evidence and the durable CommandRun store remain the state authorities.

## Agent stream

```text
GET /api/v3/streams/agent/runs/{run_id}
```

The projection contains only stable product fields: run/project/thread identity, objective, actor, trigger, status, lifecycle timestamps, counts, the latest sanitized activity identity/type/title/status and the explicit hidden-reasoning boundary.

It does not stream prompt/provider payloads, token/reasoning payloads, tool arguments, governance metadata, raw OTLP/Phoenix spans or hidden chain-of-thought.

## CommandRun stream

```text
GET /api/v3/streams/command-runs/{command_run_id}
```

The projection contains command/run identity, state, bound ConfigSnapshot identity, WorkbenchContext, requester, lifecycle timestamps, result status, produced evidence IDs and the latest typed CommandEvent identity/type/state/time.

It deliberately excludes:

```text
parameters
outputs
artifact_paths
free-form result/event messages
host filesystem paths
```

The full governed CommandRun remains available from the separate Control Plane when explicit inspection is required.

## Transport semantics

- Event IDs are deterministic digests of the normalized projection, so an unchanged snapshot has the same event identity.
- `Last-Event-ID` is honored to avoid replaying an unchanged snapshot after reconnect.
- Heartbeat comments keep idle HTTP connections alive without fabricating product events.
- Blocking SQLite/audit reads execute outside the async event loop.
- A source disappearing or becoming invalid closes the stream so the browser's native EventSource reconnect semantics can retry safely.
- `?once=true` returns one standards-compatible SSE frame for deterministic API/CI acceptance; the Workbench uses the normal continuous endpoint.

## Workbench integration

- Added a typed native `EventSource` hook.
- Agent Workbench uses Agent SSE as an invalidation signal and then refreshes the canonical V3 Agent run projection.
- Command Palette no longer polls an active CommandRun every 600 ms.
- CommandRun SSE triggers an explicit full Control API record refresh; SSE does not become a second authority for full command details.
- If SSE is unavailable there is no hidden timed-poll fallback. The Run Inspector exposes an explicit manual `Refresh run` action.
- Existing Control Plane availability checks remain independent from CommandRun lifecycle streaming.

## Runtime behavior

`run_workspace.py` retains the configured read-only CommandRun database path even if the Control Plane has not created the SQLite file yet. This lets Workspace start first and observe the CommandRun store as soon as it appears, without creating it or requiring an Evidence Plane restart.

## API boundary

Additive GET-only routes:

```text
GET /api/v3/streams/status
GET /api/v3/streams/agent/runs/{run_id}
GET /api/v3/streams/command-runs/{command_run_id}
```

No Control Plane mutation route is added to the Evidence Plane.

## Acceptance

V3-4 tests cover deterministic event identity, state-change event identity, sanitized stream payloads, read-only SQLite/audit access, SSE content type/headers, missing-source behavior, dynamic command-store appearance and native EventSource client lifecycle. The existing Ubuntu and Windows Workspace API matrix remains enabled.
