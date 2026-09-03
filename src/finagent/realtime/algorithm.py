from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Protocol

from finagent.realtime.events import CanonicalRealtimeEvent
from finagent.realtime.projections import RealtimeProjectionSnapshot, RealtimeProjector
from finagent.realtime.sources import (
    DataAdmissibilityDecision,
    MarketDataSource,
    MarketDataSubscription,
    StrategyFreshnessBudget,
)


def _canonical_hash(payload: object, *, prefix: str) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:24]}"


class StreamingAlgorithm(Protocol):
    def on_event(
        self,
        event: CanonicalRealtimeEvent,
        state: RealtimeProjectionSnapshot,
    ) -> object | None: ...


@dataclass(frozen=True, slots=True)
class AlgorithmRunReport:
    source_profile_id: str
    subscription_id: str
    processed_event_count: int
    algorithm_event_count: int
    blocked_event_count: int
    output_count: int
    blocked_decisions: tuple[DataAdmissibilityDecision, ...]
    final_projection: RealtimeProjectionSnapshot
    outputs: tuple[object, ...]
    schema_version: str = "finagent.algorithm-streaming-run-report.v1"

    def __post_init__(self) -> None:
        if min(
            self.processed_event_count,
            self.algorithm_event_count,
            self.blocked_event_count,
            self.output_count,
        ) < 0:
            raise ValueError("algorithm run counters must be non-negative")
        if self.algorithm_event_count + self.blocked_event_count != self.processed_event_count:
            raise ValueError("algorithm + blocked event counts must equal processed events")
        if self.output_count != len(self.outputs):
            raise ValueError("output_count must equal outputs length")
        if self.blocked_event_count != len(self.blocked_decisions):
            raise ValueError("blocked_event_count must equal blocked decisions length")
        if any(item.allowed for item in self.blocked_decisions):
            raise ValueError("blocked decisions cannot contain allowed decisions")

    @property
    def report_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="algorithm-streaming-run")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "source_profile_id": self.source_profile_id,
            "subscription_id": self.subscription_id,
            "processed_event_count": self.processed_event_count,
            "algorithm_event_count": self.algorithm_event_count,
            "blocked_event_count": self.blocked_event_count,
            "output_count": self.output_count,
            "blocked_decisions": [item.to_dict() for item in self.blocked_decisions],
            "final_projection_id": self.final_projection.snapshot_id,
            "final_semantic_state_id": self.final_projection.semantic_state_id,
            "engineering_only": True,
            "algorithm_authority": False,
            "execution_authority": False,
            "stage_exit_authority": False,
        }
        if include_id:
            payload["report_id"] = self.report_id
        return payload


class AlgorithmRunner:
    """Run one algorithm over any canonical market-data source.

    Projection/health state always observes incoming events. Freshness policy gates only
    whether the algorithm is allowed to act on an event; rejected data remains visible in
    system state/diagnostics rather than disappearing from the runtime.
    """

    def __init__(self, *, projector: RealtimeProjector | None = None) -> None:
        self._projector = projector or RealtimeProjector()

    async def run(
        self,
        source: MarketDataSource,
        subscription: MarketDataSubscription,
        algorithm: StreamingAlgorithm,
        *,
        freshness_budget: StrategyFreshnessBudget | None = None,
    ) -> AlgorithmRunReport:
        processed = 0
        algorithm_events = 0
        blocked: list[DataAdmissibilityDecision] = []
        outputs: list[object] = []

        async for event in source.subscribe(subscription):
            self._projector.apply(event)
            processed += 1
            if freshness_budget is not None:
                decision = freshness_budget.assess(source.timing_profile, event)
                if not decision.allowed:
                    blocked.append(decision)
                    continue
            state = self._projector.snapshot()
            result = algorithm.on_event(event, state)
            algorithm_events += 1
            if result is not None:
                outputs.append(result)

        final_projection = self._projector.snapshot()
        return AlgorithmRunReport(
            source_profile_id=source.timing_profile.profile_id,
            subscription_id=subscription.subscription_id,
            processed_event_count=processed,
            algorithm_event_count=algorithm_events,
            blocked_event_count=len(blocked),
            output_count=len(outputs),
            blocked_decisions=tuple(blocked),
            final_projection=final_projection,
            outputs=tuple(outputs),
        )
