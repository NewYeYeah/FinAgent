from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Mapping, Sequence

from finagent.domain._validation import require_non_empty
from finagent.domain.assets import AssetId
from finagent.domain.experiments import ArtifactRef
from finagent.sandbox import FeatureSandboxRequest, LocalFeatureSandbox

from .domain import AgentTask
from .generated_features import (
    FeatureCodeValidator,
    FeatureSpec,
    GeneratedFeatureArtifact,
    SQLiteGeneratedFeatureStore,
)
from .providers import LLMCallStore, LLMProvider, LLMRequest, LLMResponse
from .templates import ExperimentTemplate


@dataclass(frozen=True, slots=True)
class LLMFeatureGenerationPolicy:
    model: str
    generator_version: str = "llm-feature-generator-1"
    max_lookback: int = 252
    max_output_tokens: int = 3500
    temperature: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "model", require_non_empty(self.model, "model"))
        object.__setattr__(self, "generator_version", require_non_empty(self.generator_version, "generator_version"))
        if isinstance(self.max_lookback, bool) or not isinstance(self.max_lookback, int) or self.max_lookback < 1:
            raise ValueError("max_lookback must be an integer >= 1")
        if isinstance(self.max_output_tokens, bool) or not isinstance(self.max_output_tokens, int) or self.max_output_tokens < 1:
            raise ValueError("max_output_tokens must be an integer >= 1")
        if self.temperature is not None and not 0.0 <= float(self.temperature) <= 2.0:
            raise ValueError("temperature must be in [0, 2]")


@dataclass(frozen=True, slots=True)
class LLMFeatureGenerationResult:
    artifact: GeneratedFeatureArtifact
    provider_response: LLMResponse
    prompt_hash: str


class LLMFeatureGenerationError(ValueError):
    pass


class LLMFeatureGenerator:
    """Generate one bounded feature program, validate it locally, then smoke-test it."""

    def __init__(
        self,
        *,
        provider: LLMProvider,
        policy: LLMFeatureGenerationPolicy,
        validator: FeatureCodeValidator | None = None,
        sandbox: LocalFeatureSandbox | None = None,
        feature_store: SQLiteGeneratedFeatureStore | None = None,
        call_store: LLMCallStore | None = None,
        clock: Callable[[], datetime] | None = None,
        request_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self.provider = provider
        self.policy = policy
        self.validator = validator or FeatureCodeValidator()
        self.sandbox = sandbox or LocalFeatureSandbox(validator=self.validator)
        self.feature_store = feature_store
        self.call_store = call_store
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.request_id_factory = request_id_factory or (lambda: f"llm-feature-{uuid.uuid4().hex}")

    def generate(
        self,
        *,
        task: AgentTask,
        approved_input_fields: Sequence[str],
        smoke_inputs: Mapping[str, Sequence[int | float | None]],
    ) -> LLMFeatureGenerationResult:
        fields = tuple(require_non_empty(str(value), "approved input field") for value in approved_input_fields)
        if not fields or len(set(fields)) != len(fields):
            raise ValueError("approved_input_fields must be non-empty and unique")
        if set(smoke_inputs) != set(fields):
            raise ValueError("smoke_inputs must contain exactly the approved input fields")
        request = self._request(task, fields)
        try:
            response = self.provider.complete(request)
        except Exception as exc:
            if self.call_store is not None:
                self.call_store.record_failure(task.task_id, request, self.provider.provider_name, exc)
            raise
        try:
            spec, source = self.parse_feature(response.output_text, fields)
            validation = self.validator.validate(source)
            sandbox_inputs = {name: smoke_inputs[name] for name in spec.input_fields}
            smoke = self.sandbox.run(FeatureSandboxRequest(spec, source, sandbox_inputs))
            artifact = GeneratedFeatureArtifact(
                spec=spec,
                source=source,
                validation=validation,
                generated_at=self.clock(),
                generator_id=f"{self.provider.provider_name}:{self.policy.model}:{self.policy.generator_version}",
                smoke_output_digest=smoke.output_digest,
                metadata={"task_id": task.task_id, "prompt_hash": request.prompt_hash},
            )
            if self.feature_store is not None:
                self.feature_store.register(artifact)
        except Exception as exc:
            if self.call_store is not None:
                self.call_store.record_response(task.task_id, request, response, planning_valid=False, validation_error=str(exc))
            raise
        if self.call_store is not None:
            self.call_store.record_response(task.task_id, request, response, planning_valid=True)
        return LLMFeatureGenerationResult(artifact, response, request.prompt_hash)

    def _request(self, task: AgentTask, fields: tuple[str, ...]) -> LLMRequest:
        instructions = (
            "You are the FinAgent feature generator. Return one deterministic pure-Python feature. "
            "The source must define exactly def compute_feature(inputs), use no imports, no file/network/process access, "
            "and return a list with the same length as its inputs containing only finite numbers or null-equivalent None. "
            "Use only approved input fields. Warm-up observations may be None. Do not generate portfolio, risk, execution, "
            "registry, validation or broker code."
        )
        payload = {
            "research_task": task.objective,
            "task_metadata": dict(task.metadata),
            "approved_input_fields": list(fields),
            "max_lookback": self.policy.max_lookback,
            "function_contract": "compute_feature(inputs) -> list[float|None]",
        }
        return LLMRequest(
            request_id=self.request_id_factory(),
            model=self.policy.model,
            instructions=instructions,
            input_text=json.dumps(payload, sort_keys=True, ensure_ascii=False),
            schema_name="finagent_generated_feature",
            response_schema=self._schema(fields),
            max_output_tokens=self.policy.max_output_tokens,
            temperature=self.policy.temperature,
            metadata={"task_id": task.task_id, "generator_version": self.policy.generator_version},
        )

    def _schema(self, fields: tuple[str, ...]) -> Mapping[str, object]:
        return {
            "type": "object",
            "properties": {
                "feature_id": {"type": "string"},
                "name": {"type": "string"},
                "description": {"type": "string"},
                "hypothesis": {"type": "string"},
                "input_fields": {
                    "type": "array", "minItems": 1, "uniqueItems": True,
                    "items": {"type": "string", "enum": list(fields)},
                },
                "lookback": {"type": "integer", "minimum": 1, "maximum": self.policy.max_lookback},
                "source": {"type": "string"},
            },
            "required": ["feature_id", "name", "description", "hypothesis", "input_fields", "lookback", "source"],
            "additionalProperties": False,
        }

    def parse_feature(self, output_text: str, approved_fields: tuple[str, ...]) -> tuple[FeatureSpec, str]:
        try:
            payload = json.loads(output_text)
        except json.JSONDecodeError as exc:
            raise LLMFeatureGenerationError(f"feature output is not valid JSON: {exc}") from exc
        required = {"feature_id", "name", "description", "hypothesis", "input_fields", "lookback", "source"}
        if not isinstance(payload, dict) or set(payload) != required:
            raise LLMFeatureGenerationError("feature output fields must exactly match the frozen schema")
        raw_fields = payload["input_fields"]
        if not isinstance(raw_fields, list) or not raw_fields:
            raise LLMFeatureGenerationError("input_fields must be a non-empty list")
        fields = tuple(str(value) for value in raw_fields)
        if len(set(fields)) != len(fields) or not set(fields).issubset(set(approved_fields)):
            raise LLMFeatureGenerationError("generated input_fields must be unique and policy-approved")
        feature_id = require_non_empty(str(payload["feature_id"]), "feature_id")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", feature_id):
            raise LLMFeatureGenerationError("feature_id contains unsupported characters")
        lookback = payload["lookback"]
        if isinstance(lookback, bool) or not isinstance(lookback, int) or not 1 <= lookback <= self.policy.max_lookback:
            raise LLMFeatureGenerationError("generated lookback is outside policy bounds")
        spec = FeatureSpec(
            feature_id=feature_id,
            name=str(payload["name"]),
            description=str(payload["description"]),
            hypothesis=str(payload["hypothesis"]),
            input_fields=fields,
            lookback=lookback,
        )
        return spec, require_non_empty(str(payload["source"]), "source")


def generated_feature_template(
    artifact: GeneratedFeatureArtifact,
    *,
    template_id: str,
    evaluator_id: str,
    dataset: ArtifactRef,
    universe: tuple[AssetId, ...],
    parameter_names: frozenset[str] = frozenset(),
    seed: int = 0,
) -> ExperimentTemplate:
    """Bridge a validated generated feature into the existing approved-template research path."""
    return ExperimentTemplate(
        template_id=template_id,
        evaluator_id=evaluator_id,
        dataset=dataset,
        code=artifact.code_artifact_ref(),
        universe=universe,
        parameter_names=parameter_names,
        seed=seed,
        metadata={
            "generated_feature_id": artifact.spec.feature_id,
            "generated_feature_digest": artifact.digest,
            "factor_artifact_id": artifact.factor_artifact_ref().artifact_id,
        },
    )
