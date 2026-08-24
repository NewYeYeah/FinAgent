from __future__ import annotations

import hashlib
import platform
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Mapping

from finagent.domain.experiments import (
    ArtifactRef,
    ExperimentResult,
    ExperimentRun,
    ExperimentRunStatus,
    ExperimentSpec,
)


@dataclass(frozen=True, slots=True)
class ExperimentEvaluation:
    metrics: Mapping[str, float]
    passed: bool
    produced_artifacts: tuple[ArtifactRef, ...] = ()
    notes: str = ""


class ExperimentRunner:
    """Deterministic experiment lifecycle coordinator.

    The runner owns registry state transitions, not experiment logic.  A research
    agent may later choose or compose an evaluator, but the lifecycle itself remains
    ordinary auditable Python code.
    """

    def __init__(
        self,
        registry,
        *,
        clock: Callable[[], datetime] | None = None,
        run_id_factory: Callable[[], str] | None = None,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        self.registry = registry
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.run_id_factory = run_id_factory or (lambda: f"run-{uuid.uuid4().hex}")
        self.environment = dict(environment or self._default_environment())

    @staticmethod
    def _default_environment() -> dict[str, str]:
        return {
            "python": platform.python_version(),
            "implementation": platform.python_implementation(),
            "platform": sys.platform,
        }

    def run(
        self,
        spec: ExperimentSpec,
        evaluator: Callable[[ExperimentSpec], ExperimentEvaluation],
    ) -> ExperimentResult:
        self.registry.register_artifact(spec.dataset)
        self.registry.register_artifact(spec.code)
        for artifact in spec.parent_artifacts:
            self.registry.register_artifact(artifact)
        self.registry.register_experiment(spec)

        run_id = self.run_id_factory()
        started_at = self.clock()
        running = ExperimentRun(
            run_id=run_id,
            spec_fingerprint=spec.fingerprint,
            status=ExperimentRunStatus.RUNNING,
            started_at=started_at,
            environment=self.environment,
        )
        self.registry.register_run(running)

        try:
            evaluation = evaluator(spec)
            if not isinstance(evaluation, ExperimentEvaluation):
                raise TypeError("evaluator must return ExperimentEvaluation")
            result = ExperimentResult(
                run_id=run_id,
                metrics=evaluation.metrics,
                passed=evaluation.passed,
                produced_artifacts=evaluation.produced_artifacts,
                notes=evaluation.notes,
            )
            for artifact in evaluation.produced_artifacts:
                self.registry.register_artifact(artifact)
            self.registry.register_result(result)
            finished_at = self.clock()
            stdout_digest = hashlib.sha256(
                repr((dict(result.metrics), result.passed, result.notes)).encode("utf-8")
            ).hexdigest()
            self.registry.register_run(
                ExperimentRun(
                    run_id=run_id,
                    spec_fingerprint=spec.fingerprint,
                    status=ExperimentRunStatus.SUCCEEDED,
                    started_at=started_at,
                    finished_at=finished_at,
                    environment=self.environment,
                    stdout_digest=stdout_digest,
                )
            )
            return result
        except Exception as exc:
            finished_at = self.clock()
            failure_digest = hashlib.sha256(
                f"{type(exc).__name__}:{exc}".encode("utf-8")
            ).hexdigest()
            self.registry.register_run(
                ExperimentRun(
                    run_id=run_id,
                    spec_fingerprint=spec.fingerprint,
                    status=ExperimentRunStatus.FAILED,
                    started_at=started_at,
                    finished_at=finished_at,
                    environment=self.environment,
                    stdout_digest=failure_digest,
                )
            )
            raise
