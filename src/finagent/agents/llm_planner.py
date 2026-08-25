from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Callable, Mapping

from finagent.domain._validation import require_non_empty
from finagent.domain.metrics import MetricObjective

from .domain import AgentTask
from .planning import ExperimentVariant, ResearchBudget, ResearchPlan
from .providers import LLMCallStore, LLMProvider, LLMRequest, LLMResponse
from .templates import ExperimentTemplateRegistry


@dataclass(frozen=True, slots=True)
class LLMPlanningPolicy:
    model: str
    planner_version: str = "llm-planner-1"
    max_variants: int = 8
    max_tool_calls: int = 32
    max_failed_experiments: int = 0
    allow_new_family: bool = True
    allowed_primary_metrics: tuple[str, ...] = ("validation_sharpe",)
    allowed_tie_break_metrics: tuple[str, ...] = ("turnover",)
    alpha: float = 0.05
    correction_method: str = "holm"
    max_output_tokens: int = 2500
    temperature: float | None = None
    research_program_id: str = ""
    metric_objectives: Mapping[str, MetricObjective | str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "model", require_non_empty(self.model, "model"))
        object.__setattr__(
            self,
            "planner_version",
            require_non_empty(self.planner_version, "planner_version"),
        )
        for name in ("max_variants", "max_tool_calls", "max_output_tokens"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be an integer >= 1")
        if self.max_failed_experiments < 0 or self.max_failed_experiments > self.max_variants:
            raise ValueError("invalid max_failed_experiments")
        primary = tuple(require_non_empty(v, "metric") for v in self.allowed_primary_metrics)
        tie = tuple(require_non_empty(v, "metric") for v in self.allowed_tie_break_metrics)
        if not primary or not tie:
            raise ValueError("allowed metric lists cannot be empty")
        object.__setattr__(self, "allowed_primary_metrics", primary)
        object.__setattr__(self, "allowed_tie_break_metrics", tie)
        object.__setattr__(self, "research_program_id", self.research_program_id.strip())
        normalized_objectives: dict[str, MetricObjective] = {}
        for name, objective in self.metric_objectives.items():
            normalized_objectives[require_non_empty(str(name), "metric name")] = MetricObjective(
                objective
            )
        object.__setattr__(self, "metric_objectives", MappingProxyType(normalized_objectives))
        if not 0.0 < self.alpha < 1.0:
            raise ValueError("alpha must be in (0, 1)")
        if self.temperature is not None and not 0.0 <= float(self.temperature) <= 2.0:
            raise ValueError("temperature must be in [0, 2]")

    def objective_for(self, metric: str, *, tie_break: bool) -> MetricObjective:
        if metric in self.metric_objectives:
            return self.metric_objectives[metric]
        # Backward-compatible defaults are explicit by role, not inferred from name.
        return MetricObjective.MINIMIZE if tie_break else MetricObjective.MAXIMIZE


@dataclass(frozen=True, slots=True)
class LLMPlanningResult:
    plan: ResearchPlan
    provider_response: LLMResponse
    prompt_hash: str


class LLMPlanValidationError(ValueError):
    pass


class LLMResearchPlanner:
    """LLM proposes a bounded ResearchPlan; deterministic code validates it."""

    def __init__(
        self,
        *,
        provider: LLMProvider,
        templates: ExperimentTemplateRegistry,
        policy: LLMPlanningPolicy,
        call_store: LLMCallStore | None = None,
        request_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self.provider = provider
        self.templates = templates
        self.policy = policy
        self.call_store = call_store
        self.request_id_factory = request_id_factory or (lambda: f"llm-plan-{uuid.uuid4().hex}")

    def plan(self, task: AgentTask) -> LLMPlanningResult:
        request = self._request(task)
        try:
            response = self.provider.complete(request)
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
            plan = self.parse_plan(task, response.output_text)
        except Exception as exc:
            if self.call_store is not None:
                self.call_store.record_response(
                    task.task_id,
                    request,
                    response,
                    planning_valid=False,
                    validation_error=str(exc),
                )
            raise
        if self.call_store is not None:
            self.call_store.record_response(
                task.task_id,
                request,
                response,
                planning_valid=True,
            )
        return LLMPlanningResult(plan, response, request.prompt_hash)

    def _request(self, task: AgentTask) -> LLMRequest:
        catalog = []
        for template_id in self.templates.names():
            template = self.templates.get(template_id)
            catalog.append(
                {
                    "template_id": template.template_id,
                    "parameter_names": sorted(template.parameter_names),
                }
            )
        instructions = (
            "You are the FinAgent research planner. Propose a finite experiment family only from "
            "the supplied approved template catalog. Do not choose statistical thresholds, metric "
            "directions, portfolio weights, execution settings, broker actions, code, model lifecycle "
            "stages, or research budgets. Keep variants meaningfully distinct and within the declared "
            "maximum."
        )
        input_payload = {
            "research_task": task.objective,
            "task_metadata": dict(task.metadata),
            "approved_templates": catalog,
            "allowed_primary_metrics": list(self.policy.allowed_primary_metrics),
            "allowed_tie_break_metrics": list(self.policy.allowed_tie_break_metrics),
            "max_variants": self.policy.max_variants,
        }
        return LLMRequest(
            request_id=self.request_id_factory(),
            model=self.policy.model,
            instructions=instructions,
            input_text=json.dumps(input_payload, sort_keys=True, ensure_ascii=False),
            schema_name="finagent_research_plan",
            response_schema=self._schema(),
            max_output_tokens=self.policy.max_output_tokens,
            temperature=self.policy.temperature,
            metadata={
                "task_id": task.task_id,
                "planner_version": self.policy.planner_version,
                "research_program_id": self.policy.research_program_id,
            },
        )

    def _schema(self) -> Mapping[str, object]:
        return {
            "type": "object",
            "properties": {
                "family_id": {"type": "string"},
                "research_question": {"type": "string"},
                "primary_metric": {
                    "type": "string",
                    "enum": list(self.policy.allowed_primary_metrics),
                },
                "template_id": {"type": "string", "enum": list(self.templates.names())},
                "tie_break_metric": {
                    "type": "string",
                    "enum": list(self.policy.allowed_tie_break_metrics),
                },
                "variants": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": self.policy.max_variants,
                    "items": {
                        "type": "object",
                        "properties": {
                            "variant_id": {"type": "string"},
                            "experiment_id": {"type": "string"},
                            "hypothesis": {"type": "string"},
                            "parameters": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "name": {"type": "string"},
                                        "value": {
                                            "anyOf": [
                                                {"type": "string"},
                                                {"type": "number"},
                                                {"type": "boolean"},
                                            ]
                                        },
                                    },
                                    "required": ["name", "value"],
                                    "additionalProperties": False,
                                },
                            },
                        },
                        "required": ["variant_id", "experiment_id", "hypothesis", "parameters"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": [
                "family_id",
                "research_question",
                "primary_metric",
                "template_id",
                "tie_break_metric",
                "variants",
            ],
            "additionalProperties": False,
        }

    def parse_plan(self, task: AgentTask, output_text: str) -> ResearchPlan:
        try:
            payload = json.loads(output_text)
        except json.JSONDecodeError as exc:
            raise LLMPlanValidationError(f"planner output is not valid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise LLMPlanValidationError("planner output must be a JSON object")
        allowed = {
            "family_id",
            "research_question",
            "primary_metric",
            "template_id",
            "tie_break_metric",
            "variants",
        }
        extra = set(payload) - allowed
        if extra:
            raise LLMPlanValidationError(f"unexpected planner fields: {sorted(extra)}")

        template_id = require_non_empty(str(payload.get("template_id", "")), "template_id")
        template = self.templates.get(template_id)
        primary_metric = require_non_empty(
            str(payload.get("primary_metric", "")),
            "primary_metric",
        )
        if primary_metric not in self.policy.allowed_primary_metrics:
            raise LLMPlanValidationError("primary_metric is not policy-approved")
        tie_break_metric = require_non_empty(
            str(payload.get("tie_break_metric", "")),
            "tie_break_metric",
        )
        if tie_break_metric not in self.policy.allowed_tie_break_metrics:
            raise LLMPlanValidationError("tie_break_metric is not policy-approved")

        raw_variants = payload.get("variants")
        if not isinstance(raw_variants, list) or not 1 <= len(raw_variants) <= self.policy.max_variants:
            raise LLMPlanValidationError("variants must be a non-empty list within max_variants")

        variants: list[ExperimentVariant] = []
        for item in raw_variants:
            if not isinstance(item, dict):
                raise LLMPlanValidationError("each variant must be an object")
            if set(item) != {"variant_id", "experiment_id", "hypothesis", "parameters"}:
                raise LLMPlanValidationError("variant fields must match the frozen schema")
            raw_params = item["parameters"]
            if not isinstance(raw_params, list):
                raise LLMPlanValidationError("variant parameters must be an array")
            params: dict[str, str | int | float | bool] = {}
            for parameter in raw_params:
                if not isinstance(parameter, dict) or set(parameter) != {"name", "value"}:
                    raise LLMPlanValidationError("each parameter must contain exactly name and value")
                name = require_non_empty(str(parameter["name"]), "parameter name")
                if name in params:
                    raise LLMPlanValidationError(f"duplicate variant parameter {name!r}")
                value = parameter["value"]
                if not isinstance(value, (str, int, float, bool)):
                    raise LLMPlanValidationError("parameter values must be scalar")
                params[name] = value
            if set(params) != set(template.parameter_names):
                raise LLMPlanValidationError(
                    "variant parameters must exactly match template parameters "
                    f"{sorted(template.parameter_names)}"
                )
            variants.append(
                ExperimentVariant(
                    variant_id=self._safe_id(str(item["variant_id"]), "variant_id"),
                    experiment_id=self._safe_id(str(item["experiment_id"]), "experiment_id"),
                    parameters=params,
                    hypothesis=str(item["hypothesis"]),
                )
            )

        budget = ResearchBudget(
            max_tool_calls=self.policy.max_tool_calls,
            max_experiments=self.policy.max_variants,
            max_family_size=self.policy.max_variants,
            max_failed_experiments=self.policy.max_failed_experiments,
            allow_new_family=self.policy.allow_new_family,
            allow_promotion_request=False,
        )
        return ResearchPlan(
            plan_id=f"{self.policy.planner_version}:{task.task_id}",
            planner_version=self.policy.planner_version,
            family_id=self._safe_id(str(payload.get("family_id", "")), "family_id"),
            research_question=require_non_empty(
                str(payload.get("research_question", "")),
                "research_question",
            ),
            primary_metric=primary_metric,
            template_id=template_id,
            variants=tuple(variants),
            budget=budget,
            tie_break_metric=tie_break_metric,
            alpha=self.policy.alpha,
            correction_method=self.policy.correction_method,
            metadata={
                "source": "llm",
                "provider": self.provider.provider_name,
                "model": self.policy.model,
            },
            program_id=self.policy.research_program_id,
            primary_metric_objective=self.policy.objective_for(
                primary_metric,
                tie_break=False,
            ),
            tie_break_metric_objective=self.policy.objective_for(
                tie_break_metric,
                tie_break=True,
            ),
        )

    @staticmethod
    def _safe_id(value: str, field_name: str) -> str:
        value = require_non_empty(value, field_name)
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", value):
            raise LLMPlanValidationError(
                f"{field_name} must match [A-Za-z0-9][A-Za-z0-9._:-]{{0,127}}"
            )
        return value
