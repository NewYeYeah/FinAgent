from __future__ import annotations

import ctypes
import math
import os
from dataclasses import dataclass
from typing import Literal

ParallelWorkload = Literal["cpu", "io", "subprocess"]


def _positive_int_env(name: str) -> int | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def _logical_cpu_count() -> int:
    process_count = getattr(os, "process_cpu_count", None)
    if callable(process_count):
        value = process_count()
        if value:
            return max(1, int(value))
    get_affinity = getattr(os, "sched_getaffinity", None)
    if callable(get_affinity):
        try:
            return max(1, len(get_affinity(0)))
        except OSError:
            pass
    return max(1, int(os.cpu_count() or 1))


def _available_memory_mb() -> int | None:
    override = _positive_int_env("FINAGENT_AVAILABLE_MEMORY_MB")
    if override is not None:
        return override

    if os.name == "nt":
        class MemoryStatusEx(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = MemoryStatusEx()
        status.dwLength = ctypes.sizeof(MemoryStatusEx)
        try:
            ok = ctypes.windll.kernel32.GlobalMemoryStatusEx(  # type: ignore[attr-defined]
                ctypes.byref(status)
            )
        except (AttributeError, OSError):
            ok = 0
        if ok:
            return max(1, int(status.ullAvailPhys // (1024 * 1024)))

    if hasattr(os, "sysconf"):
        try:
            pages = int(os.sysconf("SC_AVPHYS_PAGES"))
            page_size = int(os.sysconf("SC_PAGE_SIZE"))
            if pages > 0 and page_size > 0:
                return max(1, pages * page_size // (1024 * 1024))
        except (OSError, ValueError, TypeError):
            pass
    return None


@dataclass(frozen=True, slots=True)
class ParallelPlan:
    workers: int
    workload: ParallelWorkload
    work_items: int
    cpu_count: int
    available_memory_mb: int | None
    cpu_budget: int
    memory_budget: int | None
    configured_cap: int | None
    hard_cap: int
    mode: str

    def to_dict(self) -> dict[str, object]:
        return {
            "workers": self.workers,
            "workload": self.workload,
            "work_items": self.work_items,
            "cpu_count": self.cpu_count,
            "available_memory_mb": self.available_memory_mb,
            "cpu_budget": self.cpu_budget,
            "memory_budget": self.memory_budget,
            "configured_cap": self.configured_cap,
            "hard_cap": self.hard_cap,
            "mode": self.mode,
        }


@dataclass(frozen=True, slots=True)
class AutoParallelPolicy:
    """Resolve a conservative cross-platform worker budget from runtime resources.

    The policy is deliberately a *budget*, not an authoritative research input.  Worker
    count may vary by machine without changing research artifacts or evidence digests.
    ``FINAGENT_MAX_WORKERS`` can cap the automatic result and
    ``FINAGENT_PARALLEL_MODE=serial`` forces one worker for debugging.
    """

    cpu_fraction: float = 0.75
    memory_fraction: float = 0.65
    hard_cap: int = 16

    def __post_init__(self) -> None:
        if not 0 < self.cpu_fraction <= 1:
            raise ValueError("cpu_fraction must be in (0, 1]")
        if not 0 < self.memory_fraction <= 1:
            raise ValueError("memory_fraction must be in (0, 1]")
        if self.hard_cap < 1:
            raise ValueError("hard_cap must be >= 1")

    def resolve(
        self,
        work_items: int,
        *,
        workload: ParallelWorkload = "cpu",
        per_worker_memory_mb: int = 256,
        configured_cap: int | None = None,
    ) -> ParallelPlan:
        if work_items < 0:
            raise ValueError("work_items must be >= 0")
        if per_worker_memory_mb < 1:
            raise ValueError("per_worker_memory_mb must be >= 1")
        if configured_cap is not None and configured_cap < 1:
            raise ValueError("configured_cap must be >= 1")

        mode = os.environ.get("FINAGENT_PARALLEL_MODE", "auto").strip().lower() or "auto"
        cpu_count = _logical_cpu_count()
        available_memory_mb = _available_memory_mb()
        if mode in {"serial", "off", "disabled", "0"}:
            return ParallelPlan(
                workers=1,
                workload=workload,
                work_items=work_items,
                cpu_count=cpu_count,
                available_memory_mb=available_memory_mb,
                cpu_budget=1,
                memory_budget=1 if available_memory_mb is not None else None,
                configured_cap=1,
                hard_cap=self.hard_cap,
                mode="serial",
            )

        cpu_multiplier = 2.0 if workload == "io" else 1.0
        cpu_budget = max(1, math.floor(cpu_count * self.cpu_fraction * cpu_multiplier))
        memory_budget: int | None = None
        if available_memory_mb is not None:
            memory_budget = max(
                1,
                math.floor(
                    available_memory_mb * self.memory_fraction / per_worker_memory_mb
                ),
            )

        env_cap = _positive_int_env("FINAGENT_MAX_WORKERS")
        caps = [self.hard_cap, cpu_budget]
        if memory_budget is not None:
            caps.append(memory_budget)
        if configured_cap is not None:
            caps.append(configured_cap)
        if env_cap is not None:
            caps.append(env_cap)
        if work_items > 0:
            caps.append(work_items)
        workers = max(1, min(caps))
        return ParallelPlan(
            workers=workers,
            workload=workload,
            work_items=work_items,
            cpu_count=cpu_count,
            available_memory_mb=available_memory_mb,
            cpu_budget=cpu_budget,
            memory_budget=memory_budget,
            configured_cap=min(
                value for value in (configured_cap, env_cap) if value is not None
            )
            if configured_cap is not None or env_cap is not None
            else None,
            hard_cap=self.hard_cap,
            mode="auto",
        )


DEFAULT_PARALLEL_POLICY = AutoParallelPolicy()
