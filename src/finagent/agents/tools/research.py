from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Mapping, Protocol, Sequence

from finagent.domain.assets import AssetId, AssetType
from finagent.domain.experiment_family import (
    CorrectionMethod,
    ExperimentFamily,
    ExperimentFamilyStatus,
)
from finagent.domain.experiments import ArtifactRef, ArtifactType, ExperimentResult, ExperimentSpec
from finagent.domain.model_registry import ModelStage, validate_model_transition
from finagent.research.family_validation import ExperimentFamilyValidator
from finagent.research.query import SQLiteResearchQueryService
from finagent.research.registry import SQLiteResearchRegistry
from finagent.research.runner import ExperimentEvaluation, ExperimentRunner

from ..domain import AgentAction, AgentRunContext, ToolMode
from .base import FunctionTool, ToolSpec


Evaluator = Callable[[ExperimentSpec], ExperimentEvaluation]


class ExperimentEvaluatorRegistry:
    """Finite registry of approved deterministic experiment evaluators/templates."""

    def __init__(self) -> None:
        self._evaluators: dict[str, Evaluator] = {}

    def register(self, evaluator_id: str, evaluator: Evaluator) -> None:
        evaluator_id = str(evaluator_id).strip()
        if not evaluator_id:
            raise ValueError("evaluator_id must be non-empty")
        if evaluator_id in self._evaluators:
            raise ValueError(f"evaluator {evaluator_id!r} is already registered")
        if not callable(evaluator):
            raise TypeError("evaluator must be callable")
        self._evaluators[evaluator_id] = evaluator

    def get(self, evaluator_id: str) -> Evaluator:
        try:
            return self._evaluators[evaluator_id]
        except KeyError as exc:
            raise KeyError(f"unregistered evaluator {evaluator_id!r}") from exc

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._evaluators))


@dataclass(frozen=True, slots=True)
class FamilyValidationInputs:
    trial_returns: Mapping[str, Sequence[float]]
    pvalues: Mapping[str, float]


class FamilyValidationInputProvider(Protocol):
    def __call__(self, family_id: str) -> FamilyValidationInputs: ...


@dataclass(frozen=True, slots=True)
class FamilyValidationPolicy:
    """Fixed statistical gate parameters unavailable for Agent mutation."""

    dsr_probability_threshold: float = 0.95
    pbo_threshold: float = 0.5
    pbo_blocks: int = 8
    bootstrap_samples: int = 1000
    bootstrap_block_size: int | None = None
    seed: int = 0

    def __post_init__(self) -> None:
        if not 0.0 < self.dsr_probability_threshold < 1.0:
            raise ValueError("dsr_probability_threshold must be in (0, 1)")
        if not 0.0 <= self.pbo_threshold <= 1.0:
            raise ValueError("pbo_threshold must be in [0, 1]")
        if self.pbo_blocks < 4 or self.pbo_blocks % 2:
            raise ValueError("pbo_blocks must be an even integer >= 4")
        if self.bootstrap_samples < 1:
            raise ValueError("bootstrap_samples must be >= 1")
        if self.bootstrap_block_size is not None and self.bootstrap_block_size < 1:
            raise ValueError("bootstrap_block_size must be >= 1 when supplied")
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise TypeError("seed must be an int")


@dataclass(slots=True)
class ResearchToolDependencies:
    registry: SQLiteResearchRegistry
    query: SQLiteResearchQueryService
    runner: ExperimentRunner
    family_validator: ExperimentFamilyValidator
    evaluators: ExperimentEvaluatorRegistry
    validation_input_provider: FamilyValidationInputProvider
    validation_policy: FamilyValidationPolicy = FamilyValidationPolicy()
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)


def _artifact_payload(ref: ArtifactRef) -> dict[str, object]:
    return {
        "artifact_id": ref.artifact_id,
        "artifact_type": ref.artifact_type.value,
        "version": ref.version,
        "digest": ref.digest,
        "uri": ref.uri,
    }


def _artifact_from_payload(value: object, field_name: str) -> ArtifactRef:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    required = {"artifact_id", "artifact_type", "version", "digest"}
    missing = required - set(value)
    if missing:
        raise ValueError(f"{field_name} missing keys: {sorted(missing)}")
    return ArtifactRef(
        artifact_id=str(value["artifact_id"]),
        artifact_type=ArtifactType(str(value["artifact_type"])),
        version=str(value["version"]),
        digest=str(value["digest"]),
        uri=str(value.get("uri", "")),
    )


def _asset_payload(asset: AssetId) -> dict[str, str]:
    return {
        "symbol": asset.symbol,
        "asset_type": asset.asset_type.value,
        "venue": asset.venue,
        "currency": asset.currency,
    }


def _asset_from_payload(value: object) -> AssetId:
    if not isinstance(value, Mapping):
        raise TypeError("each universe entry must be a mapping")
    return AssetId(
        symbol=str(value["symbol"]),
        asset_type=AssetType(str(value.get("asset_type", AssetType.EQUITY.value))),
        venue=str(value.get("venue", "")),
        currency=str(value.get("currency", "USD")),
    )


def _experiment_payload(spec: ExperimentSpec) -> dict[str, object]:
    return {
        "experiment_id": spec.experiment_id,
        "hypothesis": spec.hypothesis,
        "fingerprint": spec.fingerprint,
        "dataset": _artifact_payload(spec.dataset),
        "code": _artifact_payload(spec.code),
        "universe": [_asset_payload(asset) for asset in spec.universe],
        "parameters": dict(spec.parameters),
        "seed": spec.seed,
        "parent_artifacts": [_artifact_payload(ref) for ref in spec.parent_artifacts],
        "metadata": dict(spec.metadata),
    }


def _family_payload(family: ExperimentFamily) -> dict[str, object]:
    return {
        "family_id": family.family_id,
        "research_question": family.research_question,
        "primary_metric": family.primary_metric,
        "created_at": family.created_at.isoformat(),
        "alpha": family.alpha,
        "correction_method": family.correction_method.value,
        "status": family.status.value,
        "metadata": dict(family.metadata),
    }


def _result_payload(result: ExperimentResult | None) -> dict[str, object] | None:
    if result is None:
        return None
    return {
        "run_id": result.run_id,
        "metrics": dict(result.metrics),
        "passed": result.passed,
        "produced_artifacts": [_artifact_payload(ref) for ref in result.produced_artifacts],
        "notes": result.notes,
    }


def _model_payload(model) -> dict[str, object]:
    return {
        "model_id": model.model_id,
        "family": model.family,
        "artifact": _artifact_payload(model.artifact),
        "stage": model.stage.value,
        "created_at": model.created_at.isoformat(),
        "metrics": dict(model.metrics),
        "metadata": dict(model.metadata),
    }


def _require_mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    return value


def _require_sequence(value: object, field_name: str) -> Sequence[object]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise TypeError(f"{field_name} must be a sequence")
    return value


def build_research_tools(deps: ResearchToolDependencies) -> tuple[FunctionTool, ...]:
    def inspect_data_contract(arguments, context):
        return {
            "canonical_path": (
                "DataAdapter -> ResearchDataset/ResearchSplit -> FeatureWindow -> "
                "AlphaModel/RiskModel"
            ),
            "feature_shape": "(time, asset, feature)",
            "label_shape": "(time, asset, label)",
            "dtype": "float64",
            "point_in_time_clock": "available_at",
            "time_range": "[start, end)",
            "cross_module_dataframe_contract": False,
            "outer_test_exposed_to_agent": False,
        }

    def list_experiment_families(arguments, context):
        raw_status = arguments.get("status")
        status = ExperimentFamilyStatus(str(raw_status)) if raw_status is not None else None
        families = deps.query.list_families(status=status)
        return {"families": [_family_payload(family) for family in families]}

    def inspect_experiment_family(arguments, context):
        family_id = str(arguments["family_id"])
        family = deps.registry.get_family(family_id)
        members = deps.registry.family_members(family_id)
        return {
            "family": _family_payload(family),
            "members": [
                {
                    "experiment_id": member.experiment_id,
                    "role": member.role,
                    "added_at": member.added_at.isoformat(),
                }
                for member in members
            ],
        }

    def list_experiments(arguments, context):
        family_id = arguments.get("family_id")
        if family_id is None:
            specs = deps.query.list_experiments()
        else:
            specs = tuple(
                deps.registry.get_experiment(member.experiment_id)
                for member in deps.registry.family_members(str(family_id))
            )
        return {"experiments": [_experiment_payload(spec) for spec in specs]}

    def inspect_experiment(arguments, context):
        experiment_id = str(arguments["experiment_id"])
        snapshot = deps.query.experiment_snapshot(experiment_id)
        return {
            "experiment": _experiment_payload(snapshot.spec),
            "runs": [
                {
                    "run_id": run.run_id,
                    "status": run.status.value,
                    "started_at": run.started_at.isoformat(),
                    "finished_at": run.finished_at.isoformat() if run.finished_at else None,
                    "stdout_digest": run.stdout_digest,
                }
                for run in snapshot.runs
            ],
            "latest_result": _result_payload(snapshot.latest_result),
        }

    def compare_experiment_results(arguments, context):
        experiment_ids = tuple(
            str(value) for value in _require_sequence(arguments["experiment_ids"], "experiment_ids")
        )
        if len(experiment_ids) < 2:
            raise ValueError("compare_experiment_results requires at least two experiment_ids")
        if len(set(experiment_ids)) != len(experiment_ids):
            raise ValueError("experiment_ids cannot contain duplicates")
        metric = str(arguments["metric"]).strip()
        if not metric:
            raise ValueError("metric must be non-empty")
        comparisons: list[dict[str, object]] = []
        for experiment_id in experiment_ids:
            result = deps.query.latest_result_for_experiment(experiment_id)
            comparisons.append(
                {
                    "experiment_id": experiment_id,
                    "run_id": result.run_id if result else None,
                    "metric": metric,
                    "value": (
                        float(result.metrics[metric])
                        if result is not None and metric in result.metrics
                        else None
                    ),
                    "passed": result.passed if result is not None else None,
                }
            )
        return {"metric": metric, "comparisons": comparisons}

    def inspect_model_registry(arguments, context):
        raw_stage = arguments.get("stage")
        stage = ModelStage(str(raw_stage)) if raw_stage is not None else None
        return {"models": [_model_payload(model) for model in deps.query.list_models(stage=stage)]}

    def inspect_model_history(arguments, context):
        model_id = str(arguments["model_id"])
        model = deps.registry.get_model(model_id)
        history = deps.registry.model_history(model_id)
        return {
            "model": _model_payload(model),
            "history": [
                {
                    "from_stage": event.from_stage.value,
                    "to_stage": event.to_stage.value,
                    "changed_at": event.changed_at.isoformat(),
                    "reason": event.reason,
                    "actor": event.actor,
                }
                for event in history
            ],
        }

    def create_experiment_family(arguments, context):
        metadata_raw = arguments.get("metadata", {})
        metadata = _require_mapping(metadata_raw, "metadata")
        family = ExperimentFamily(
            family_id=str(arguments["family_id"]),
            research_question=str(arguments["research_question"]),
            primary_metric=str(arguments["primary_metric"]),
            created_at=deps.clock(),
            alpha=float(arguments.get("alpha", 0.05)),
            correction_method=CorrectionMethod(str(arguments.get("correction_method", "holm"))),
            metadata={str(key): str(value) for key, value in metadata.items()},
        )
        deps.registry.register_family(family)
        return {"family": _family_payload(family)}

    def register_experiment(arguments, context):
        family_id = str(arguments["family_id"])
        family = deps.registry.get_family(family_id)
        if family.status is not ExperimentFamilyStatus.OPEN:
            raise ValueError("experiments can only be registered into an OPEN family")

        evaluator_id = str(arguments["evaluator_id"]).strip()
        deps.evaluators.get(evaluator_id)  # fail before registry mutation if not approved

        dataset = _artifact_from_payload(arguments["dataset"], "dataset")
        code = _artifact_from_payload(arguments["code"], "code")
        universe_raw = _require_sequence(arguments["universe"], "universe")
        universe = tuple(_asset_from_payload(value) for value in universe_raw)
        parameters_raw = _require_mapping(arguments.get("parameters", {}), "parameters")
        parameters: dict[str, str | int | float | bool] = {}
        for key, value in parameters_raw.items():
            if isinstance(value, (str, int, float, bool)):
                parameters[str(key)] = value
            else:
                raise TypeError("experiment parameters must be scalar str/int/float/bool values")
        metadata_raw = _require_mapping(arguments.get("metadata", {}), "metadata")
        metadata = {str(key): str(value) for key, value in metadata_raw.items()}
        existing_evaluator = metadata.get("evaluator_id")
        if existing_evaluator is not None and existing_evaluator != evaluator_id:
            raise ValueError("metadata.evaluator_id conflicts with evaluator_id")
        metadata["evaluator_id"] = evaluator_id
        parent_raw = _require_sequence(arguments.get("parent_artifacts", ()), "parent_artifacts")
        parents = tuple(
            _artifact_from_payload(value, "parent_artifacts") for value in parent_raw
        )
        spec = ExperimentSpec(
            experiment_id=str(arguments["experiment_id"]),
            hypothesis=str(arguments["hypothesis"]),
            dataset=dataset,
            code=code,
            universe=universe,
            parameters=parameters,
            seed=int(arguments.get("seed", 0)),
            parent_artifacts=parents,
            metadata=metadata,
        )
        deps.registry.register_artifact(dataset)
        deps.registry.register_artifact(code)
        for parent in parents:
            deps.registry.register_artifact(parent)
        deps.registry.register_experiment(spec)
        membership = deps.registry.add_experiment_to_family(
            family_id,
            spec.experiment_id,
            added_at=deps.clock(),
            role=str(arguments.get("role", "variant")),
        )
        return {
            "experiment": _experiment_payload(spec),
            "membership": {
                "family_id": membership.family_id,
                "experiment_id": membership.experiment_id,
                "added_at": membership.added_at.isoformat(),
                "role": membership.role,
            },
        }

    def run_experiment(arguments, context):
        experiment_id = str(arguments["experiment_id"])
        spec = deps.registry.get_experiment(experiment_id)
        evaluator_id = spec.metadata.get("evaluator_id")
        if not evaluator_id:
            raise ValueError("experiment is missing an approved evaluator_id")
        evaluator = deps.evaluators.get(str(evaluator_id))
        result = deps.runner.run(spec, evaluator)
        return {"result": _result_payload(result)}

    def freeze_experiment_family(arguments, context):
        family = deps.registry.transition_family(
            str(arguments["family_id"]), ExperimentFamilyStatus.FROZEN
        )
        return {"family": _family_payload(family)}

    def validate_experiment_family_tool(arguments, context):
        family_id = str(arguments["family_id"])
        selected_experiment_id = str(arguments["selected_experiment_id"])
        inputs = deps.validation_input_provider(family_id)
        policy = deps.validation_policy
        validation = deps.family_validator.validate(
            family_id,
            trial_returns=inputs.trial_returns,
            pvalues=inputs.pvalues,
            selected_experiment_id=selected_experiment_id,
            dsr_probability_threshold=policy.dsr_probability_threshold,
            pbo_threshold=policy.pbo_threshold,
            pbo_blocks=policy.pbo_blocks,
            bootstrap_samples=policy.bootstrap_samples,
            bootstrap_block_size=policy.bootstrap_block_size,
            seed=policy.seed,
        )
        report = validation.report
        return {
            "family_id": family_id,
            "selected_experiment_id": validation.selected_experiment_id,
            "experiment_order": list(validation.experiment_order),
            "passed": report.passed,
            "multiple_testing": {
                "method": report.multiple_testing.method.value,
                "alpha": report.multiple_testing.alpha,
                "adjusted_pvalues": list(report.multiple_testing.adjusted_pvalues),
                "rejected": list(report.multiple_testing.rejected),
            },
            "deflated_sharpe": {
                "observed_sharpe": report.deflated_sharpe.observed_sharpe,
                "benchmark_sharpe": report.deflated_sharpe.benchmark_sharpe,
                "deflated_probability": report.deflated_sharpe.deflated_probability,
                "n_trials": report.deflated_sharpe.n_trials,
            },
            "pbo": report.pbo.probability_of_backtest_overfitting,
            "reality_check_pvalue": report.reality_check.pvalue,
            "validation_policy": {
                "dsr_probability_threshold": policy.dsr_probability_threshold,
                "pbo_threshold": policy.pbo_threshold,
                "pbo_blocks": policy.pbo_blocks,
                "bootstrap_samples": policy.bootstrap_samples,
                "bootstrap_block_size": policy.bootstrap_block_size,
                "seed": policy.seed,
            },
        }

    def request_model_promotion(arguments, context):
        model_id = str(arguments["model_id"])
        current = deps.registry.get_model(model_id)
        to_stage = ModelStage(str(arguments["to_stage"]))
        reason = str(arguments["reason"]).strip()
        if not reason:
            raise ValueError("reason must be non-empty")
        validate_model_transition(current.stage, to_stage)
        return {
            "request": {
                "model_id": model_id,
                "from_stage": current.stage.value,
                "to_stage": to_stage.value,
                "reason": reason,
                "requested_by": context.actor,
                "requested_at": deps.clock().isoformat(),
                "mutation_performed": False,
            }
        }

    return (
        FunctionTool(
            ToolSpec(
                name=AgentAction.INSPECT_DATA_CONTRACT.value,
                description="Inspect the frozen numerical/PIT data contract without reading market values.",
                action=AgentAction.INSPECT_DATA_CONTRACT,
                mode=ToolMode.READ,
            ),
            inspect_data_contract,
        ),
        FunctionTool(
            ToolSpec(
                name=AgentAction.LIST_EXPERIMENT_FAMILIES.value,
                description="List registered experiment families, optionally filtered by lifecycle status.",
                action=AgentAction.LIST_EXPERIMENT_FAMILIES,
                mode=ToolMode.READ,
                optional_arguments=frozenset({"status"}),
            ),
            list_experiment_families,
        ),
        FunctionTool(
            ToolSpec(
                name=AgentAction.INSPECT_EXPERIMENT_FAMILY.value,
                description="Inspect one experiment family and its immutable/current membership.",
                action=AgentAction.INSPECT_EXPERIMENT_FAMILY,
                mode=ToolMode.READ,
                required_arguments=frozenset({"family_id"}),
            ),
            inspect_experiment_family,
        ),
        FunctionTool(
            ToolSpec(
                name=AgentAction.LIST_EXPERIMENTS.value,
                description="List experiments globally or within one registered family.",
                action=AgentAction.LIST_EXPERIMENTS,
                mode=ToolMode.READ,
                optional_arguments=frozenset({"family_id"}),
            ),
            list_experiments,
        ),
        FunctionTool(
            ToolSpec(
                name=AgentAction.INSPECT_EXPERIMENT.value,
                description="Inspect a registered experiment, its runs and latest persisted result.",
                action=AgentAction.INSPECT_EXPERIMENT,
                mode=ToolMode.READ,
                required_arguments=frozenset({"experiment_id"}),
            ),
            inspect_experiment,
        ),
        FunctionTool(
            ToolSpec(
                name=AgentAction.COMPARE_EXPERIMENT_RESULTS.value,
                description="Compare one persisted metric across registered experiment results.",
                action=AgentAction.COMPARE_EXPERIMENT_RESULTS,
                mode=ToolMode.READ,
                required_arguments=frozenset({"experiment_ids", "metric"}),
            ),
            compare_experiment_results,
        ),
        FunctionTool(
            ToolSpec(
                name=AgentAction.INSPECT_MODEL_REGISTRY.value,
                description="List registered models, optionally filtered by governance stage.",
                action=AgentAction.INSPECT_MODEL_REGISTRY,
                mode=ToolMode.READ,
                optional_arguments=frozenset({"stage"}),
            ),
            inspect_model_registry,
        ),
        FunctionTool(
            ToolSpec(
                name=AgentAction.INSPECT_MODEL_HISTORY.value,
                description="Inspect one model and its append-only governance transition history.",
                action=AgentAction.INSPECT_MODEL_HISTORY,
                mode=ToolMode.READ,
                required_arguments=frozenset({"model_id"}),
            ),
            inspect_model_history,
        ),
        FunctionTool(
            ToolSpec(
                name=AgentAction.CREATE_EXPERIMENT_FAMILY.value,
                description="Create a pre-registered OPEN experiment family.",
                action=AgentAction.CREATE_EXPERIMENT_FAMILY,
                mode=ToolMode.WRITE,
                required_arguments=frozenset(
                    {"family_id", "research_question", "primary_metric"}
                ),
                optional_arguments=frozenset({"alpha", "correction_method", "metadata"}),
            ),
            create_experiment_family,
        ),
        FunctionTool(
            ToolSpec(
                name=AgentAction.REGISTER_EXPERIMENT.value,
                description="Register one approved-template experiment into an OPEN family.",
                action=AgentAction.REGISTER_EXPERIMENT,
                mode=ToolMode.WRITE,
                required_arguments=frozenset(
                    {
                        "family_id",
                        "experiment_id",
                        "hypothesis",
                        "dataset",
                        "code",
                        "universe",
                        "evaluator_id",
                    }
                ),
                optional_arguments=frozenset(
                    {"parameters", "seed", "parent_artifacts", "metadata", "role"}
                ),
            ),
            register_experiment,
        ),
        FunctionTool(
            ToolSpec(
                name=AgentAction.RUN_EXPERIMENT.value,
                description="Run a registered experiment through its approved evaluator and ExperimentRunner.",
                action=AgentAction.RUN_EXPERIMENT,
                mode=ToolMode.WRITE,
                required_arguments=frozenset({"experiment_id"}),
            ),
            run_experiment,
        ),
        FunctionTool(
            ToolSpec(
                name=AgentAction.FREEZE_EXPERIMENT_FAMILY.value,
                description="Freeze a non-empty experiment family so membership becomes immutable.",
                action=AgentAction.FREEZE_EXPERIMENT_FAMILY,
                mode=ToolMode.WRITE,
                required_arguments=frozenset({"family_id"}),
            ),
            freeze_experiment_family,
        ),
        FunctionTool(
            ToolSpec(
                name=AgentAction.VALIDATE_EXPERIMENT_FAMILY.value,
                description=(
                    "Run the fixed family-level anti-overfitting gate using trusted validation inputs."
                ),
                action=AgentAction.VALIDATE_EXPERIMENT_FAMILY,
                mode=ToolMode.WRITE,
                required_arguments=frozenset({"family_id", "selected_experiment_id"}),
            ),
            validate_experiment_family_tool,
        ),
        FunctionTool(
            ToolSpec(
                name=AgentAction.REQUEST_MODEL_PROMOTION.value,
                description=(
                    "Request, but never perform, one legal model-stage promotion. "
                    "SHADOW/LIVE requests require human approval."
                ),
                action=AgentAction.REQUEST_MODEL_PROMOTION,
                mode=ToolMode.REQUEST,
                required_arguments=frozenset({"model_id", "to_stage", "reason"}),
            ),
            request_model_promotion,
        ),
    )
