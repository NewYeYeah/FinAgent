from __future__ import annotations

import json
from datetime import UTC, datetime

from finagent.agents.domain import AgentTask
from finagent.agents.generation_checkpoint import SQLiteFeatureGenerationCheckpointStore
from finagent.agents.generated_features import SQLiteGeneratedFeatureStore
from finagent.agents.llm_feature import LLMFeatureGenerationPolicy, LLMFeatureGenerator
from finagent.agents.observability import AgentObservabilityConfig, AgentTracer
from finagent.agents.providers import (
    DeepSeekChatProvider,
    LLMRequest,
    LLMResponse,
    LLMUsage,
)
from finagent.research.resilient_candidate_generator import (
    ResilientLLMMarketFeatureCandidateGenerator,
)


NOW = datetime(2026, 8, 27, 8, 0, tzinfo=UTC)


class _Details:
    def __init__(self, reasoning_tokens: int = 0, cached_tokens: int = 0) -> None:
        self.reasoning_tokens = reasoning_tokens
        self.cached_tokens = cached_tokens


class _Usage:
    def __init__(self, completion: int, reasoning: int = 0) -> None:
        self.prompt_tokens = 100
        self.completion_tokens = completion
        self.total_tokens = 100 + completion
        self.prompt_tokens_details = _Details(cached_tokens=5)
        self.completion_tokens_details = _Details(reasoning_tokens=reasoning)


class _Message:
    def __init__(self, content: str | None, reasoning_content: str = "") -> None:
        self.content = content
        self.reasoning_content = reasoning_content


class _Choice:
    def __init__(self, content: str | None, *, finish_reason: str, reasoning: str = "") -> None:
        self.message = _Message(content, reasoning)
        self.finish_reason = finish_reason


class _ChatResponse:
    def __init__(
        self,
        content: str | None,
        *,
        finish_reason: str = "stop",
        completion: int = 100,
        reasoning_tokens: int = 0,
        reasoning_content: str = "",
        response_id: str = "resp",
    ) -> None:
        self.id = response_id
        self.model = "deepseek-v4-pro"
        self.choices = [
            _Choice(content, finish_reason=finish_reason, reasoning=reasoning_content)
        ]
        self.usage = _Usage(completion, reasoning_tokens)


class _Completions:
    def __init__(self, responses) -> None:
        self.responses = list(responses)
        self.calls = 0
        self.kwargs = []

    def create(self, **kwargs):
        self.kwargs.append(kwargs)
        response = self.responses[self.calls]
        self.calls += 1
        return response


class _Chat:
    def __init__(self, responses) -> None:
        self.completions = _Completions(responses)


class _Client:
    def __init__(self, responses) -> None:
        self.chat = _Chat(responses)


def _request() -> LLMRequest:
    return LLMRequest(
        request_id="deepseek-retry",
        model="deepseek-v4-pro",
        instructions="structured",
        input_text="x",
        schema_name="x",
        response_schema={
            "type": "object",
            "properties": {"ok": {"type": "boolean"}},
            "required": ["ok"],
            "additionalProperties": False,
        },
        max_output_tokens=50_000,
    )


def test_deepseek_empty_json_content_retries_and_records_termination_metadata() -> None:
    client = _Client(
        [
            _ChatResponse(
                None,
                completion=10_012,
                reasoning_tokens=9_980,
                reasoning_content="hidden reasoning must never be stored",
                response_id="empty",
            ),
            _ChatResponse(
                '{"ok":true}',
                completion=10_120,
                reasoning_tokens=9_900,
                reasoning_content="also hidden",
                response_id="good",
            ),
        ]
    )
    provider = DeepSeekChatProvider(
        client=client,
        max_attempts=2,
        retry_backoff_seconds=0.0,
    )
    response = provider.complete(_request())
    assert response.output_text == '{"ok":true}'
    assert response.metadata["provider_attempts"] == "2"
    assert response.metadata["reasoning_tokens"] == "9900"
    assert response.metadata["has_reasoning"] == "true"
    assert "reasoning_content" not in response.metadata
    assert client.chat.completions.calls == 2


class _SequenceProvider:
    provider_name = "sequence"

    def __init__(self, outputs: list[str]) -> None:
        self.outputs = outputs
        self.requests: list[LLMRequest] = []

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        output = self.outputs[len(self.requests) - 1]
        return LLMResponse(
            request_id=request.request_id,
            response_id=f"sequence-{len(self.requests)}",
            provider=self.provider_name,
            model=request.model,
            output_text=output,
            usage=LLMUsage(input_tokens=100, output_tokens=200, total_tokens=300),
            status="stop",
        )


def _candidate(source: str, feature_id: str = "repair-me") -> str:
    return json.dumps(
        {
            "feature_id": feature_id,
            "name": "Repair candidate",
            "description": "Generated test candidate",
            "hypothesis": "A simple return transformation may predict the next session.",
            "input_fields": ["simple_return_5"],
            "lookback": 1,
            "source": source,
        }
    )


def test_feature_generator_repairs_attribute_and_plain_list_runtime_failures(tmp_path) -> None:
    provider = _SequenceProvider(
        [
            _candidate(
                "def compute_feature(inputs):\n"
                "    output = []\n"
                "    output.append(1.0)\n"
                "    return output\n"
            ),
            _candidate(
                "def compute_feature(inputs):\n"
                "    return inputs['simple_return_5'] * 0.5\n"
            ),
            _candidate(
                "def compute_feature(inputs):\n"
                "    values = inputs['simple_return_5']\n"
                "    return [None if value is None else value * 0.5 for value in values]\n"
            ),
        ]
    )
    generator = LLMFeatureGenerator(
        provider=provider,
        policy=LLMFeatureGenerationPolicy(
            model="deepseek-v4-pro",
            max_output_tokens=50_000,
            max_validation_attempts=3,
        ),
        feature_store=SQLiteGeneratedFeatureStore(tmp_path / "features.sqlite"),
    )
    result = generator.generate(
        task=AgentTask("repair-task", "generate factor", NOW),
        approved_input_fields=("simple_return_5",),
        smoke_inputs={"simple_return_5": [0.01, -0.02, 0.03, 0.04]},
    )
    assert result.attempts == 3
    assert len(result.repair_errors) == 2
    assert "FeatureCodeValidationError" in result.repair_errors[0]
    assert "FeatureSandboxError" in result.repair_errors[1]
    assert "plain Python list" in provider.requests[1].instructions
    assert "attribute access" in provider.requests[1].input_text
    assert "can't multiply sequence" in provider.requests[2].input_text
    assert result.artifact.spec.feature_id == "repair-me"


def test_resilient_candidate_replaces_exhausted_slot_and_reuses_checkpoint(tmp_path) -> None:
    invalid = _candidate(
        "def compute_feature(inputs):\n"
        "    values = []\n"
        "    values.append(1.0)\n"
        "    return values\n",
        "bad-slot",
    )
    valid = _candidate(
        "def compute_feature(inputs):\n"
        "    values = inputs['simple_return_5']\n"
        "    return [None if value is None else -value for value in values]\n",
        "replacement-slot",
    )
    feature_store = SQLiteGeneratedFeatureStore(tmp_path / "features.sqlite")
    checkpoints = SQLiteFeatureGenerationCheckpointStore(tmp_path / "checkpoints.sqlite")
    provider = _SequenceProvider([invalid, valid])
    generator = LLMFeatureGenerator(
        provider=provider,
        policy=LLMFeatureGenerationPolicy(
            model="deepseek-v4-pro",
            max_validation_attempts=1,
        ),
        feature_store=feature_store,
    )
    resilient = ResilientLLMMarketFeatureCandidateGenerator(
        generator,
        max_candidates=1,
        max_replacements_per_candidate=1,
        checkpoint_store=checkpoints,
    )
    task = AgentTask("round-1", "generate distinct factor", NOW)
    first = resilient.generate(
        task=task,
        count=1,
        approved_input_fields=("simple_return_5",),
        smoke_inputs={"simple_return_5": [0.01, 0.02, 0.03]},
    )
    assert first[0].spec.feature_id == "replacement-slot"
    assert len(provider.requests) == 2

    class _MustNotCall:
        provider_name = "must-not-call"

        def complete(self, request):
            raise AssertionError("checkpointed candidate unexpectedly called the LLM")

    resumed = ResilientLLMMarketFeatureCandidateGenerator(
        LLMFeatureGenerator(
            provider=_MustNotCall(),
            policy=LLMFeatureGenerationPolicy(
                model="deepseek-v4-pro",
                max_validation_attempts=1,
            ),
            feature_store=feature_store,
        ),
        max_candidates=1,
        max_replacements_per_candidate=1,
        checkpoint_store=checkpoints,
    ).generate(
        task=task,
        count=1,
        approved_input_fields=("simple_return_5",),
        smoke_inputs={"simple_return_5": [0.01, 0.02, 0.03]},
    )
    assert resumed[0].digest == first[0].digest


def test_jsonl_agent_tracer_records_hierarchy_without_hidden_reasoning(tmp_path) -> None:
    path = tmp_path / "agent.jsonl"
    tracer = AgentTracer(
        AgentObservabilityConfig(
            enabled=True,
            backend="jsonl",
            jsonl_path=str(path),
            capture_content=False,
        )
    )
    with tracer.span("root", "AGENT", {"task": "a2"}):
        with tracer.span("llm", "LLM", {"reasoning_tokens": 10_000}):
            tracer.event("repair", {"error_type": "FeatureSandboxError"})
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    starts = [row for row in rows if row["event"] == "span_start"]
    assert len(starts) == 2
    assert starts[1]["parent_span_id"] == starts[0]["span_id"]
    serialized = json.dumps(rows)
    assert "reasoning_tokens" in serialized
    assert "reasoning_content" not in serialized
