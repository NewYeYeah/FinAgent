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
from finagent.sandbox import FeatureSandboxError, FeatureSandboxRequest, LocalFeatureSandbox

from .domain import AgentTask
from .generated_features import (
    FeatureCodeValidationError,
    FeatureCodeValidator,
    FeatureSpec,
    GeneratedFeatureArtifact,
    SQLiteGeneratedFeatureStore,
)
from .observability import AgentTracer
from .providers import LLMCallStore, LLMProvider, LLMRequest, LLMResponse
from .templates import ExperimentTemplate


@dataclass(frozen=True, slots=True)
class LLMFeatureGenerationPolicy:
    model: str
    generator_version: str = "llm-feature-generator-2"
    max_lookback: int = 252
    max_output_tokens: int = 50_000
    temperature: float | None = None
    max_validation_attempts: int = 3

    def __post_init__(self) -> None:
        object.__setattr__(self, "model", require_non_empty(self.model, "model"))
        object.__setattr__(
            self,
            "generator_version",
            require_non_empty(self.generator_version, "generator_version"),
        )
        if (
            isinstance(self.max_lookback, bool)
            or not isinstance(self.max_lookback, int)
            or self.max_lookback < 1
        ):
            raise ValueError("max_lookback must be an integer >= 1")
        if (
            isinstance(self.max_output_tokens, bool)
            or not isinstance(self.max_output_tokens, int)
            or self.max_output_tokens < 1
        ):
            raise ValueError("max_output_tokens must be an integer >= 1")
        if (
            isinstance(self.max_validation_attempts, bool)
            or not isinstance(self.max_validation_attempts, int)
            or self.max_validation_attempts < 1
        ):
            raise ValueError("max_validation_attempts must be an integer >= 1")
        if self.temperature is not None and not 0.0 <= float(self.temperature) <= 2.0:
            raise ValueError("temperature must be in [0, 2]")


@dataclass(frozen=True, slots=True)
class LLMFeatureGenerationResult:
    artifact: GeneratedFeatureArtifact
    provider_response: LLMResponse
    prompt_hash: str
    attempts: int = 1
    repair_errors: tuple[str, ...] = ()


class LLMFeatureGenerationError(ValueError):
    pass


class LLMCandidateRepairExhaustedError(LLMFeatureGenerationError):
    pass


def _compact_error(exc: Exception, limit: int = 1600) -> str:
    value = " ".join(str(exc).split())
    if len(value) > limit:
        value = value[:limit] + "…"
    return f"{type(exc).__name__}: {value}"


class LLMFeatureGenerator:
    """Generate one bounded feature program, repair conformance failures, then smoke-test it.

    Provider failures are handled by the provider adapter. This layer only repairs
    candidate-content failures (schema/AST/sandbox) and feeds back engineering
    conformance evidence. Market/validation/holdout evidence is never used for repair.
    """

    def __init__(
        self,
        *,
        provider: LLMProvider,
        policy: LLMFeatureGenerationPolicy,
        validator: FeatureCodeValidator | None = None,
        sandbox: LocalFeatureSandbox | None = None,
        feature_store: SQLiteGeneratedFeatureStore | None = None,
        call_store: LLMCallStore | None = None,
        tracer: AgentTracer | None = None,
        clock: Callable[[], datetime] | None = None,
        request_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self.provider = provider
        self.policy = policy
        self.validator = validator or FeatureCodeValidator()
        self.sandbox = sandbox or LocalFeatureSandbox(validator=self.validator)
        self.feature_store = feature_store
        self.call_store = call_store
        self.tracer = tracer or AgentTracer()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.request_id_factory = request_id_factory or (
            lambda: f"llm-feature-{uuid.uuid4().hex}"
        )

    def generate(
        self,
        *,
        task: AgentTask,
        approved_input_fields: Sequence[str],
        smoke_inputs: Mapping[str, Sequence[int | float | None]],
    ) -> LLMFeatureGenerationResult:
        fields = tuple(
            require_non_empty(str(value), "approved input field")
            for value in approved_input_fields
        )
        if not fields or len(set(fields)) != len(fields):
            raise ValueError("approved_input_fields must be non-empty and unique")
        if set(smoke_inputs) != set(fields):
            raise ValueError("smoke_inputs must contain exactly the approved input fields")

        request = self._request(task, fields)
        repairs: list[str] = []
        with self.tracer.span(
            "finagent.feature.generate",
            "AGENT",
            {
                "finagent.task_id": task.task_id,
                "llm.model_name": self.policy.model,
                "finagent.max_validation_attempts": self.policy.max_validation_attempts,
            },
        ) as root_span:
            for attempt in range(1, self.policy.max_validation_attempts + 1):
                try:
                    with self.tracer.span(
                        "finagent.llm.feature_completion",
                        "LLM",
                        {
                            "finagent.task_id": task.task_id,
                            "finagent.conformance_attempt": attempt,
                            "llm.model_name": request.model,
                            "finagent.prompt_hash": request.prompt_hash,
                            "llm.max_tokens": request.max_output_tokens,
                            **(
                                {"input.value": self.tracer.content(request.input_text)}
                                if self.tracer.capture_content
                                else {}
                            ),
                        },
                    ) as llm_span:
                        response = self.provider.complete(request)
                        llm_span.set_attributes(
                            {
                                "llm.token_count.prompt": response.usage.input_tokens,
                                "llm.token_count.completion": response.usage.output_tokens,
                                "llm.token_count.total": response.usage.total_tokens,
                                "finagent.reasoning_tokens": int(
                                    response.metadata.get("reasoning_tokens", "0") or 0
                                ),
                                "finagent.provider_attempts": int(
                                    response.metadata.get("provider_attempts", "1") or 1
                                ),
                                "finagent.finish_reason": response.status,
                                "finagent.latency_ms": response.latency_ms,
                                **(
                                    {"output.value": self.tracer.content(response.output_text)}
                                    if self.tracer.capture_content
                                    else {}
                                ),
                            }
                        )
                except Exception as exc:
                    if self.call_store is not None:
                        self.call_store.record_failure(
                            task.task_id,
                            request,
                            self.provider.provider_name,
                            exc,
                        )
                    raise

                try:
                    with self.tracer.span(
                        "finagent.feature.static_validation",
                        "GUARDRAIL",
                        {"finagent.conformance_attempt": attempt},
                    ):
                        spec, source = self.parse_feature(response.output_text, fields)
                        validation = self.validator.validate(source)
                    sandbox_inputs = {name: smoke_inputs[name] for name in spec.input_fields}
                    with self.tracer.span(
                        "finagent.feature.sandbox_smoke",
                        "TOOL",
                        {
                            "finagent.feature_id": spec.feature_id,
                            "finagent.lookback": spec.lookback,
                            "finagent.conformance_attempt": attempt,
                        },
                    ):
                        smoke = self.sandbox.run(
                            FeatureSandboxRequest(spec, source, sandbox_inputs)
                        )
                except (
                    LLMFeatureGenerationError,
                    FeatureCodeValidationError,
                    FeatureSandboxError,
                    ValueError,
                    TypeError,
                ) as exc:
                    error = _compact_error(exc)
                    repairs.append(error)
                    self.tracer.event(
                        "candidate_conformance_failed",
                        {
                            "attempt": attempt,
                            "error_type": type(exc).__name__,
                            "error": error,
                        },
                    )
                    if self.call_store is not None:
                        self.call_store.record_response(
                            task.task_id,
                            request,
                            response,
                            planning_valid=False,
                            validation_error=error,
                        )
                    if attempt >= self.policy.max_validation_attempts:
                        raise LLMCandidateRepairExhaustedError(
                            f"candidate {task.task_id!r} failed conformance after "
                            f"{attempt} attempts; last_error={error}"
                        ) from exc
                    request = self._repair_request(
                        task,
                        fields,
                        prior_output=response.output_text,
                        error=error,
                        repair_attempt=attempt + 1,
                    )
                    continue

                artifact = GeneratedFeatureArtifact(
                    spec=spec,
                    source=source,
                    validation=validation,
                    generated_at=self.clock(),
                    generator_id=(
                        f"{self.provider.provider_name}:{self.policy.model}:"
                        f"{self.policy.generator_version}"
                    ),
                    smoke_output_digest=smoke.output_digest,
                    metadata={
                        "task_id": task.task_id,
                        "prompt_hash": request.prompt_hash,
                        "conformance_attempts": str(attempt),
                    },
                )
                if self.feature_store is not None:
                    self.feature_store.register(artifact)
                if self.call_store is not None:
                    self.call_store.record_response(
                        task.task_id,
                        request,
                        response,
                        planning_valid=True,
                    )
                root_span.set_attributes(
                    {
                        "finagent.feature_id": artifact.spec.feature_id,
                        "finagent.feature_digest": artifact.digest,
                        "finagent.conformance_attempts": attempt,
                    }
                )
                return LLMFeatureGenerationResult(
                    artifact,
                    response,
                    request.prompt_hash,
                    attempts=attempt,
                    repair_errors=tuple(repairs),
                )
        raise AssertionError("unreachable feature-generation state")

    def _sandbox_abi(self, fields: tuple[str, ...]) -> str:
        builtins = ", ".join(self.validator.policy.allowed_builtin_calls)
        math_members = ", ".join(self.validator.policy.allowed_math_members)
        example_field = fields[0]
        example = {
            "feature_id": "example-elementwise-factor",
            "name": "Example elementwise factor",
            "description": "Schema and sandbox ABI example only.",
            "hypothesis": "Example only; do not copy this hypothesis.",
            "input_fields": [example_field],
            "lookback": 1,
            "source": (
                "def compute_feature(inputs):\n"
                f"    values = inputs[{example_field!r}]\n"
                "    return [None if value is None else -value for value in values]\n"
            ),
        }
        return (
            "RUNTIME/SANDBOX ABI (mandatory):\n"
            "- inputs is exactly dict[str, list[float | None]]. Each field is a plain "
            "Python list, never a NumPy array and never a scalar.\n"
            "- Return exactly list[float | None] with the same length as every input list.\n"
            "- Perform element-wise arithmetic with list comprehensions/for loops, zip, "
            "or enumerate. Never multiply/divide a whole input list by a float and never "
            "add two input lists expecting vector arithmetic.\n"
            "- Imports, file/network/process access, classes, lambdas, dynamic calls and "
            "object methods are forbidden. Do not use .append(), .get(), .mean(), .std(), "
            ".tolist() or any arbitrary attribute access.\n"
            f"- Allowed builtins: {builtins}.\n"
            f"- The only allowed attribute access is preloaded math.* from: {math_members}.\n"
            "- Handle None explicitly and never emit NaN/Inf. Warm-up entries may be None.\n"
            "A VALID SHAPE EXAMPLE (format/ABI only, not a requested hypothesis):\n"
            f"{json.dumps(example, ensure_ascii=False)}"
        )

    def _request(self, task: AgentTask, fields: tuple[str, ...]) -> LLMRequest:
        instructions = (
            "You are the FinAgent feature generator. Return one deterministic pure-Python "
            "factor implementation. Use only approved PIT input fields. Do not generate "
            "portfolio, risk, execution, registry, validation or broker code.\n\n"
            + self._sandbox_abi(fields)
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
            metadata={
                "task_id": task.task_id,
                "generator_version": self.policy.generator_version,
                "conformance_attempt": "1",
            },
        )

    def _repair_request(
        self,
        task: AgentTask,
        fields: tuple[str, ...],
        *,
        prior_output: str,
        error: str,
        repair_attempt: int,
    ) -> LLMRequest:
        instructions = (
            "Repair the previous FinAgent generated feature. Preserve its economic hypothesis "
            "unless the implementation itself makes that impossible. This is engineering "
            "conformance feedback only; no market validation, outer-test, holdout, promotion, "
            "paper or live evidence is available. Return a complete replacement JSON object.\n\n"
            + self._sandbox_abi(fields)
        )
        payload = {
            "research_task": task.objective,
            "approved_input_fields": list(fields),
            "max_lookback": self.policy.max_lookback,
            "previous_candidate_json": prior_output[:25_000],
            "conformance_error": error,
            "repair_attempt": repair_attempt,
        }
        return LLMRequest(
            request_id=self.request_id_factory(),
            model=self.policy.model,
            instructions=instructions,
            input_text=json.dumps(payload, sort_keys=True, ensure_ascii=False),
            schema_name="finagent_generated_feature_repair",
            response_schema=self._schema(fields),
            max_output_tokens=self.policy.max_output_tokens,
            temperature=self.policy.temperature,
            metadata={
                "task_id": task.task_id,
                "generator_version": self.policy.generator_version,
                "conformance_attempt": str(repair_attempt),
                "repair": "true",
            },
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
                    "type": "array",
                    "minItems": 1,
                    "uniqueItems": True,
                    "items": {"type": "string", "enum": list(fields)},
                },
                "lookback": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": self.policy.max_lookback,
                },
                "source": {"type": "string"},
            },
            "required": [
                "feature_id",
                "name",
                "description",
                "hypothesis",
                "input_fields",
                "lookback",
                "source",
            ],
            "additionalProperties": False,
        }

    def parse_feature(
        self,
        output_text: str,
        approved_fields: tuple[str, ...],
    ) -> tuple[FeatureSpec, str]:
        try:
            payload = json.loads(output_text)
        except json.JSONDecodeError as exc:
            raise LLMFeatureGenerationError(f"feature output is not valid JSON: {exc}") from exc
        required = {
            "feature_id",
            "name",
            "description",
            "hypothesis",
            "input_fields",
            "lookback",
            "source",
        }
        if not isinstance(payload, dict) or set(payload) != required:
            raise LLMFeatureGenerationError(
                "feature output fields must exactly match the frozen schema"
            )
        raw_fields = payload["input_fields"]
        if not isinstance(raw_fields, list) or not raw_fields:
            raise LLMFeatureGenerationError("input_fields must be a non-empty list")
        fields = tuple(str(value) for value in raw_fields)
        if len(set(fields)) != len(fields) or not set(fields).issubset(set(approved_fields)):
            raise LLMFeatureGenerationError(
                "generated input_fields must be unique and policy-approved"
            )
        feature_id = require_non_empty(str(payload["feature_id"]), "feature_id")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", feature_id):
            raise LLMFeatureGenerationError("feature_id contains unsupported characters")
        lookback = payload["lookback"]
        if (
            isinstance(lookback, bool)
            or not isinstance(lookback, int)
            or not 1 <= lookback <= self.policy.max_lookback
        ):
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
