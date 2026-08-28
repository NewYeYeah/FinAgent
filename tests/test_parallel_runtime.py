from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from finagent.research.generated_feature_eval import GeneratedFeatureMaterializer
from finagent.runtime.parallel import AutoParallelPolicy, ParallelPlan


def test_auto_parallel_policy_respects_cpu_memory_and_environment(monkeypatch) -> None:
    import finagent.runtime.parallel as parallel

    monkeypatch.setattr(parallel, "_logical_cpu_count", lambda: 16)
    monkeypatch.setattr(parallel, "_available_memory_mb", lambda: 4096)
    monkeypatch.setenv("FINAGENT_MAX_WORKERS", "6")
    plan = AutoParallelPolicy(
        cpu_fraction=0.75,
        memory_fraction=0.5,
        hard_cap=16,
    ).resolve(100, workload="subprocess", per_worker_memory_mb=512)
    assert plan.cpu_budget == 12
    assert plan.memory_budget == 4
    assert plan.workers == 4
    assert plan.configured_cap == 6

    monkeypatch.setenv("FINAGENT_PARALLEL_MODE", "serial")
    serial = AutoParallelPolicy().resolve(100, workload="io", per_worker_memory_mb=64)
    assert serial.workers == 1
    assert serial.mode == "serial"


class _FixedParallelPolicy:
    def resolve(self, work_items: int, **_: object) -> ParallelPlan:
        return ParallelPlan(
            workers=min(2, max(1, work_items)),
            workload="subprocess",
            work_items=work_items,
            cpu_count=8,
            available_memory_mb=8192,
            cpu_budget=6,
            memory_budget=8,
            configured_cap=None,
            hard_cap=16,
            mode="auto",
        )


class _FakeBatchSandbox:
    def __init__(self) -> None:
        self.limits = SimpleNamespace(memory_mb=64)
        self.max_workers: int | None = None

    def run_batch(self, requests):
        return tuple(SimpleNamespace(values=(float(value),)) for value in requests)

    def run_batches(self, batches, *, max_workers: int):
        self.max_workers = max_workers
        return tuple(self.run_batch(batch) for batch in batches)


def test_generated_feature_batches_parallelize_without_reordering_outputs() -> None:
    sandbox = _FakeBatchSandbox()
    materializer = GeneratedFeatureMaterializer(
        adapter=None,
        sandbox=sandbox,  # type: ignore[arg-type]
        batch_size=1,
        parallel_policy=_FixedParallelPolicy(),  # type: ignore[arg-type]
    )
    values = np.full((6, 1, 1), np.nan, dtype=float)
    jobs = [(index, 0, index + 1) for index in range(6)]
    materializer._run_jobs(jobs, values)  # type: ignore[arg-type]

    assert values[:, 0, 0].tolist() == [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    assert materializer.last_parallel_plan is not None
    assert materializer.last_parallel_plan.workers == 2
    assert sandbox.max_workers == 2
