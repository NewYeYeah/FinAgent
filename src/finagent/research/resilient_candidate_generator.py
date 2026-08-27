from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence

from finagent.agents.domain import AgentTask
from finagent.agents.generation_checkpoint import SQLiteFeatureGenerationCheckpointStore
from finagent.agents.generated_features import GeneratedFeatureArtifact
from finagent.agents.llm_feature import (
    LLMCandidateRepairExhaustedError,
    LLMFeatureGenerator,
)
from finagent.agents.observability import AgentTracer, default_agent_tracer


def _scope_hash(
    generator: LLMFeatureGenerator,
    task: AgentTask,
    approved_input_fields: Sequence[str],
) -> str:
    payload = {
        "task_id": task.task_id,
        "objective": task.objective,
        "metadata": dict(task.metadata),
        "approved_input_fields": list(approved_input_fields),
        "model": generator.policy.model,
        "generator_version": generator.policy.generator_version,
        "max_lookback": generator.policy.max_lookback,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


class ResilientLLMMarketFeatureCandidateGenerator:
    """Generate a bounded candidate family with repair, replacement and resume semantics."""

    def __init__(
        self,
        generator: LLMFeatureGenerator,
        *,
        max_candidates: int = 8,
        max_replacements_per_candidate: int = 2,
        checkpoint_store: SQLiteFeatureGenerationCheckpointStore | None = None,
        tracer: AgentTracer | None = None,
    ) -> None:
        if max_candidates < 1:
            raise ValueError("max_candidates must be >= 1")
        if max_replacements_per_candidate < 0:
            raise ValueError("max_replacements_per_candidate must be >= 0")
        self.generator = generator
        self.max_candidates = max_candidates
        self.max_replacements_per_candidate = max_replacements_per_candidate
        self.checkpoint_store = checkpoint_store
        self.tracer = tracer or default_agent_tracer()

    def _checkpointed(
        self,
        task: AgentTask,
        approved_input_fields: Sequence[str],
    ) -> GeneratedFeatureArtifact | None:
        if self.checkpoint_store is None:
            return None
        scope = _scope_hash(self.generator, task, approved_input_fields)
        checkpoint = self.checkpoint_store.get(task.task_id, scope)
        if checkpoint is None:
            return None
        if self.generator.feature_store is None:
            raise RuntimeError("checkpoint resume requires LLMFeatureGenerator.feature_store")
        artifact = self.generator.feature_store.get(checkpoint.artifact_digest)
        self.tracer.event(
            "candidate_checkpoint_reused",
            {
                "logical_task_id": task.task_id,
                "feature_digest": artifact.digest,
            },
        )
        return artifact

    def _register_checkpoint(
        self,
        task: AgentTask,
        approved_input_fields: Sequence[str],
        artifact: GeneratedFeatureArtifact,
        prompt_hash: str,
    ) -> None:
        if self.checkpoint_store is None:
            return
        self.checkpoint_store.register(
            task.task_id,
            _scope_hash(self.generator, task, approved_input_fields),
            artifact.digest,
            prompt_hash,
        )

    def generate(
        self,
        *,
        task: AgentTask,
        count: int,
        approved_input_fields: Sequence[str],
        smoke_inputs: Mapping[str, Sequence[int | float | None]],
    ) -> tuple[GeneratedFeatureArtifact, ...]:
        if not 1 <= count <= self.max_candidates:
            raise ValueError("candidate count exceeds LLM market feature budget")
        artifacts: list[GeneratedFeatureArtifact] = []
        digests: set[str] = set()
        feature_ids: set[str] = set()

        for index in range(count):
            logical_task = AgentTask(
                task_id=f"{task.task_id}:feature:{index + 1:02d}",
                objective=(
                    f"{task.objective}\nGenerate distinct bounded candidate {index + 1} of {count}. "
                    "Prefer an economically interpretable hypothesis and do not imitate prior candidates."
                ),
                created_at=task.created_at,
                metadata={
                    **dict(task.metadata),
                    "candidate_index": str(index + 1),
                    "candidate_count": str(count),
                },
            )
            artifact = self._checkpointed(logical_task, approved_input_fields)
            if artifact is None:
                last_error: Exception | None = None
                for replacement in range(self.max_replacements_per_candidate + 1):
                    current_task = logical_task
                    if replacement:
                        current_task = AgentTask(
                            task_id=logical_task.task_id,
                            objective=(
                                f"{logical_task.objective}\nPrevious implementations for this "
                                "logical candidate slot exhausted engineering conformance repair. "
                                "Propose a fresh implementation or a distinct hypothesis using the "
                                "same approved inputs. Do not use any market validation evidence."
                            ),
                            created_at=logical_task.created_at,
                            metadata={
                                **dict(logical_task.metadata),
                                "candidate_replacement": str(replacement),
                            },
                        )
                    try:
                        result = self.generator.generate(
                            task=current_task,
                            approved_input_fields=approved_input_fields,
                            smoke_inputs=smoke_inputs,
                        )
                    except LLMCandidateRepairExhaustedError as exc:
                        last_error = exc
                        self.tracer.event(
                            "candidate_replacement_requested",
                            {
                                "logical_task_id": logical_task.task_id,
                                "replacement": replacement + 1,
                                "error_type": type(exc).__name__,
                            },
                        )
                        continue
                    candidate = result.artifact
                    if candidate.digest in digests or candidate.spec.feature_id in feature_ids:
                        last_error = ValueError(
                            "LLM generated a duplicate feature candidate inside one frozen family"
                        )
                        self.tracer.event(
                            "candidate_duplicate_rejected",
                            {
                                "logical_task_id": logical_task.task_id,
                                "feature_id": candidate.spec.feature_id,
                                "feature_digest": candidate.digest,
                            },
                        )
                        continue
                    artifact = candidate
                    self._register_checkpoint(
                        logical_task,
                        approved_input_fields,
                        candidate,
                        result.prompt_hash,
                    )
                    break
                if artifact is None:
                    assert last_error is not None
                    raise RuntimeError(
                        f"logical candidate {logical_task.task_id!r} exhausted bounded "
                        "repair/replacement attempts"
                    ) from last_error

            if artifact.digest in digests or artifact.spec.feature_id in feature_ids:
                raise ValueError("checkpointed feature duplicates another candidate in this family")
            digests.add(artifact.digest)
            feature_ids.add(artifact.spec.feature_id)
            artifacts.append(artifact)
        return tuple(artifacts)
