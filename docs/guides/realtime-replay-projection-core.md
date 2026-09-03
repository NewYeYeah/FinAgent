# RT-R0 / RT-R1 / RT-R2 Realtime Replay and Projection Core

This guide defines the provider-neutral realtime foundation that can be implemented and validated before a real U.S. market-data or PAPER broker interface is available.

The project authority frontier remains US-D3. This implementation advances only the implementation frontier and does not alter `docs/status.toml` or Issue #125.

## RT-R0 — Canonical realtime events

All future live/replay sources must emit the same typed event envelope:

```text
event_id          content-addressed FinAgent identity
source            provider/gateway identity
source_event_id   provider-native event identity
kind              typed event kind
event_time        source/business timestamp
received_at       FinAgent receive timestamp
sequence          source-local sequence
schema_version    explicit contract version
payload           typed payload
```

`event_time` and `received_at` are intentionally distinct. Latency is never hidden by replacing source time with local receipt time.

Implemented event types:

- `QuoteEvent`
- `BarEvent`
- `MarketStatusEvent`
- `AccountStatusEvent`
- `OrderEvent`
- `TradeEvent`
- `OrderErrorEvent`
- `ConnectionEvent`

The contracts are provider-neutral. MT5 is expected to become one future adapter, not the owner of downstream state semantics.

### Identity rules

`event_id` is derived from the complete canonical event document. `(source, source_event_id)` is treated as a provider identity key.

During projection:

```text
same event_id again
-> exact duplicate; semantic state unchanged

same (source, source_event_id), different event_id
-> content conflict; fail closed
```

This prevents a reconnecting provider from silently rewriting an already observed provider event.

### Persisted event parsing

`realtime_event_from_dict()` strictly reconstructs a typed event from JSON and verifies both schema and `event_id`. A modified payload with an unchanged stored `event_id` is rejected.

## RT-R1 — ReplayGateway

`ReplayGateway` consumes canonical events and emits deterministic engineering-only replay batches.

Frozen v1 scenarios:

```text
NORMAL
DUPLICATE
OUT_OF_ORDER
STALE_QUOTE
DISCONNECT_RECONNECT
```

The gateway does not manufacture research or market authority. Every `ReplayBatch` explicitly carries false market-data, execution, status and stage-exit authority.

### Duplicate

An exact canonical event is delivered twice. The projector must not double-apply portfolio or execution state.

### Out of order

The first two source events are swapped. The projector records a sequence regression but an older quote must not overwrite a newer quote.

### Stale quote

The first quote's `received_at` is delayed while preserving its source `event_time`. This exercises stale-data health diagnostics without changing source payload semantics.

### Disconnect / reconnect

Replay control events inject a deterministic disconnect and recovery pair. This validates connection-state reducers before any real MT5 reconnect scenario is used as acceptance evidence.

## RT-R2 — Projection core

`RealtimeProjector` is the canonical state reducer. It currently builds the following provider-neutral projections:

```text
Market state
  latest quote per symbol
  latest bar per symbol/interval
  latest market status

Portfolio state
  signed lots derived from unique TradeEvent deal identities

Execution state
  latest order lifecycle per client_order_id
  immutable broker deals
  latest order errors

Account state
  latest account status per account_id

System health state
  connection status
  duplicate count
  out-of-order count
  stale-event count
  future-event count
  last source sequence
```

A later strategy-runtime increment will add strategy-decision projection; broker adapters must not invent that state.

### Ordering semantics

Semantic state uses source/business ordering rather than arrival order for latest-value projections:

```text
(event_time, sequence, received_at, event_id)
```

An older event arriving later is retained in health/event-log evidence but does not regress the latest quote, bar, account or order state.

### Idempotence and deal identity

Exact duplicate `event_id` values do not reapply semantic state. In particular, a duplicate `TradeEvent` cannot double the signed portfolio lots.

A repeated `broker_deal_id` with different event content fails closed.

### Two hashes

The snapshot exposes two identities:

- `semantic_state_id`: business state only;
- `snapshot_id`: business state plus replay/health diagnostics and event-log digest.

Therefore a duplicate replay can have the same semantic state as normal replay while still producing a different diagnostic snapshot.

### Restart reconstruction

A process restart is validated by:

```text
canonical events
-> JSON documents
-> strict typed reconstruction
-> fresh RealtimeProjector
-> snapshot
```

The reconstructed `snapshot_id`, `semantic_state_id`, and event-log digest must exactly match the original replay.

This is the initial restart model. Snapshot checkpoint restoration can be added later, but replay from the append-only canonical event log remains the ground-truth recovery path.

## Local Windows / Conda validation

```powershell
conda activate finagent
cd D:\PythonWorkspace\FinAgent

git fetch origin
git checkout rt-replay-projection-core
git pull --ff-only
```

Run focused regressions:

```powershell
pytest -q tests\test_realtime_replay_projection.py
```

Run the deterministic replay fixture:

```powershell
python scripts\run_realtime_replay_fixture.py `
  --output reports\development\realtime_replay_projection_fixture.json
```

Required fixture results:

```text
restart_reconstruction_matches = true
DUPLICATE.duplicate_event_count = 1
OUT_OF_ORDER.out_of_order_event_count = 1
STALE_QUOTE.stale_event_count = 1
DISCONNECT_RECONNECT has replay-connection
```

Run strict static checks:

```powershell
ruff check `
  src\finagent\realtime `
  scripts\run_realtime_replay_fixture.py `
  tests\test_realtime_replay_projection.py

mypy --strict `
  src\finagent\realtime `
  scripts\run_realtime_replay_fixture.py

python -m py_compile `
  src\finagent\realtime\events.py `
  src\finagent\realtime\replay.py `
  src\finagent\realtime\projections.py `
  src\finagent\realtime\serialization.py `
  scripts\run_realtime_replay_fixture.py
```

## Authority boundary

A passing RT replay fixture proves only that provider-neutral event/replay/projection code behaves deterministically under controlled faults.

It does not prove:

- real U.S. market-data freshness;
- MT5-M1 source acceptance;
- broker account truth;
- order submission or fill semantics;
- PAPER safety;
- real Alpha;
- live-capital readiness.

All replay and projection artifacts therefore retain false market-data/broker/execution/status/stage/live authority.

## Next implementation handoff

After this core is fixture validated, the next implementation increment should add an MT5 market-data adapter that maps read-only MT5 tick/bar/connection observations into these canonical events. FX may be used as a transport fixture, but U.S. MT5-M1 acceptance remains a separate future broker/source evidence gate.
