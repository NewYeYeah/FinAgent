# Automatic Parallel Runtime

FinAgent uses a shared runtime worker-budget policy for workloads whose units are
independent and deterministic. Parallelism is an execution detail only: worker count is
never written into authoritative research identities or evidence digests.

## Automatic budget

`finagent.runtime.AutoParallelPolicy` resolves workers from:

- process-visible logical CPU count / CPU affinity;
- currently available physical memory;
- a conservative CPU fraction (75%) and memory fraction (65%);
- workload size;
- a hard safety cap.

No worker argument is required for normal use. Optional operational overrides are:

```text
FINAGENT_MAX_WORKERS=<positive integer>   # cap, not a research parameter
FINAGENT_PARALLEL_MODE=serial             # deterministic debugging / constrained hosts
```

`FINAGENT_AVAILABLE_MEMORY_MB` exists for container/testing overrides and should not be
part of a research protocol.

## Parallelized surfaces

### Generated-feature materialization

Independent sandbox batches can execute concurrently. The canonical
`LocalFeatureSandbox` starts resource-limited child processes on the caller thread, then
waits for already-started children concurrently. This avoids invoking POSIX `preexec_fn`
from worker threads while retaining sandbox CPU/memory limits.

`sandbox_batch_size` remains a batching/IPC amortization parameter. It does **not** set
parallel worker count. Existing frozen research configurations therefore keep their
identity semantics.

### Workspace startup

Evidence JSON parsing, V2 raw-report loading and JSONL ledger inspection use ordered
thread pools with an automatic I/O budget. Results are reduced in deterministic path
order, so duplicate/conflict semantics do not depend on task completion order.

The resolved non-authoritative runtime plans are visible in `/api/v1/health` under
`parallelism` for operational diagnosis.

## Deliberately serial surfaces

State transitions, SQLite research registries, reserve governance, promotion decisions,
broker/order mutation and any operation whose order is part of the protocol remain
serial. Parallelism must not turn a governance boundary into a race condition.
