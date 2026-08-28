from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Mapping

from .semantic import EvidenceAuthority, EvidenceContractError


class WidgetSurface(str, Enum):
    AGENT = "agent"
    RESEARCH = "research"
    LIVE = "live"


class WidgetRenderer(str, Enum):
    METRIC_GROUP = "metric_group"
    TABLE = "table"
    LINE = "line"
    BAR = "bar"
    SCATTER = "scatter"
    HEATMAP = "heatmap"
    FOREST = "forest"
    WATERFALL = "waterfall"
    FUNNEL = "funnel"
    SANKEY = "sankey"
    DAG = "dag"
    TIMELINE = "timeline"
    CODE = "code"


@dataclass(frozen=True, slots=True)
class FinWidgetParameter:
    name: str
    value_type: str
    required: bool = False
    description: str = ""
    default: str = ""

    def __post_init__(self) -> None:
        if not self.name or not self.value_type:
            raise EvidenceContractError("widget parameter name/type must be non-empty")

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "value_type": self.value_type,
            "required": self.required,
            "description": self.description,
            "default": self.default,
        }


@dataclass(frozen=True, slots=True)
class FinWidgetSpec:
    widget_id: str
    version: str
    surface: WidgetSurface
    question: str
    evidence_types: tuple[str, ...]
    data_endpoint: str
    data_schema: str
    renderer: WidgetRenderer
    parameters: tuple[FinWidgetParameter, ...] = ()
    link_keys: tuple[str, ...] = ()
    lineage_refs: tuple[str, ...] = ()
    authority: EvidenceAuthority = EvidenceAuthority.AUTHORITATIVE
    ai_visible: bool = True
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in (
            "widget_id",
            "version",
            "question",
            "data_endpoint",
            "data_schema",
        ):
            if not str(getattr(self, name)).strip():
                raise EvidenceContractError(f"FinWidgetSpec.{name} must be non-empty")
        evidence_types = tuple(str(value).strip() for value in self.evidence_types)
        if not evidence_types or any(not value for value in evidence_types):
            raise EvidenceContractError("widget evidence_types must be non-empty")
        if len(set(evidence_types)) != len(evidence_types):
            raise EvidenceContractError("widget evidence_types must be unique")
        parameter_names = {value.name for value in self.parameters}
        if len(parameter_names) != len(self.parameters):
            raise EvidenceContractError("widget parameters must be unique")
        link_keys = tuple(str(value).strip() for value in self.link_keys)
        if any(not value for value in link_keys) or len(set(link_keys)) != len(link_keys):
            raise EvidenceContractError("widget link_keys must be unique non-empty names")
        unknown_links = set(link_keys) - parameter_names
        if unknown_links:
            raise EvidenceContractError(
                f"widget link_keys are not declared parameters: {sorted(unknown_links)}"
            )
        lineage_refs = tuple(str(value).strip() for value in self.lineage_refs)
        if any(not value for value in lineage_refs):
            raise EvidenceContractError("widget lineage_refs must be non-empty")
        object.__setattr__(self, "evidence_types", evidence_types)
        object.__setattr__(self, "link_keys", link_keys)
        object.__setattr__(self, "lineage_refs", lineage_refs)
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    def to_dict(self) -> dict[str, object]:
        return {
            "widget_id": self.widget_id,
            "version": self.version,
            "surface": self.surface.value,
            "question": self.question,
            "evidence_types": list(self.evidence_types),
            "data_endpoint": self.data_endpoint,
            "data_schema": self.data_schema,
            "renderer": self.renderer.value,
            "parameters": [value.to_dict() for value in self.parameters],
            "link_keys": list(self.link_keys),
            "lineage_refs": list(self.lineage_refs),
            "authority": self.authority.value,
            "ai_visible": self.ai_visible,
            "metadata": dict(self.metadata),
        }


def _parameters(*names: str) -> tuple[FinWidgetParameter, ...]:
    return tuple(FinWidgetParameter(name=name, value_type="string") for name in names)


def default_widget_specs() -> tuple[FinWidgetSpec, ...]:
    """First frozen semantic catalog for the future React/FastAPI Workspace.

    These are contracts, not rendered widgets.  Endpoints are intentionally stable
    logical API paths for V1; V0 does not start an HTTP server.
    """

    values = (
        FinWidgetSpec(
            widget_id="research.program.overview",
            version="v1",
            surface=WidgetSurface.RESEARCH,
            question="Where is this ResearchProgram in the governed evidence lifecycle?",
            evidence_types=(
                "ashare_robust_research_program",
                "ashare_portfolio_validation",
            ),
            data_endpoint="/api/v1/programs/{program_id}/overview",
            data_schema="finagent.visualization.program-overview.v1",
            renderer=WidgetRenderer.METRIC_GROUP,
            parameters=_parameters("program_id"),
            link_keys=("program_id",),
            lineage_refs=("program_id",),
        ),
        FinWidgetSpec(
            widget_id="research.factor.evidence_matrix",
            version="v1",
            surface=WidgetSurface.RESEARCH,
            question="Which candidates survive predictive, stability and statistical gates?",
            evidence_types=("ashare_robust_research_program",),
            data_endpoint="/api/v1/programs/{program_id}/factors",
            data_schema="finagent.visualization.factor-evidence-matrix.v1",
            renderer=WidgetRenderer.TABLE,
            parameters=_parameters("program_id", "fold_id"),
            link_keys=("program_id", "fold_id"),
            lineage_refs=("program_id",),
        ),
        FinWidgetSpec(
            widget_id="research.factor.gate_matrix",
            version="v1",
            surface=WidgetSurface.RESEARCH,
            question="Why did each factor pass or fail the preregistered robust gate?",
            evidence_types=("ashare_robust_research_program",),
            data_endpoint="/api/v1/programs/{program_id}/factors/gates",
            data_schema="finagent.visualization.factor-gate-matrix.v1",
            renderer=WidgetRenderer.HEATMAP,
            parameters=_parameters("program_id"),
            link_keys=("program_id",),
            lineage_refs=("program_id",),
        ),
        FinWidgetSpec(
            widget_id="research.factor.statistical_forest",
            version="v1",
            surface=WidgetSurface.RESEARCH,
            question="Which factor effects remain statistically credible after dependence and multiplicity controls?",
            evidence_types=(
                "ashare_factor_research_acceptance",
                "ashare_robust_research_program",
            ),
            data_endpoint="/api/v1/programs/{program_id}/factors/statistics",
            data_schema="finagent.visualization.factor-statistical-forest.v1",
            renderer=WidgetRenderer.FOREST,
            parameters=_parameters("program_id"),
            link_keys=("program_id",),
            lineage_refs=("program_id",),
        ),
        FinWidgetSpec(
            widget_id="a4.portfolio.gross_net_nav",
            version="v1",
            surface=WidgetSurface.RESEARCH,
            question="What portion of gross portfolio performance survives execution friction?",
            evidence_types=("ashare_portfolio_validation",),
            data_endpoint="/api/v1/a4/{validation_id}/nav",
            data_schema="finagent.visualization.a4-nav-series.v1",
            renderer=WidgetRenderer.LINE,
            parameters=_parameters("validation_id", "fold_id", "date_range"),
            link_keys=("validation_id", "fold_id", "date_range"),
            lineage_refs=("validation_id",),
        ),
        FinWidgetSpec(
            widget_id="a4.portfolio.drawdown",
            version="v1",
            surface=WidgetSurface.RESEARCH,
            question="When and how deeply did the execution-aware portfolio draw down?",
            evidence_types=("ashare_portfolio_validation",),
            data_endpoint="/api/v1/a4/{validation_id}/drawdown",
            data_schema="finagent.visualization.a4-drawdown-series.v1",
            renderer=WidgetRenderer.LINE,
            parameters=_parameters("validation_id", "fold_id", "date_range"),
            link_keys=("validation_id", "fold_id", "date_range"),
            lineage_refs=("validation_id",),
            authority=EvidenceAuthority.DERIVED,
        ),
        FinWidgetSpec(
            widget_id="a4.execution.order_funnel",
            version="v1",
            surface=WidgetSurface.RESEARCH,
            question="How much desired trading intent survives compilation and execution?",
            evidence_types=("ashare_portfolio_validation", "ashare_execution_ledger"),
            data_endpoint="/api/v1/a4/{validation_id}/execution/funnel",
            data_schema="finagent.visualization.a4-order-funnel.v1",
            renderer=WidgetRenderer.FUNNEL,
            parameters=_parameters("validation_id", "fold_id", "date_range"),
            link_keys=("validation_id", "fold_id", "date_range"),
            lineage_refs=("validation_id",),
        ),
        FinWidgetSpec(
            widget_id="a4.execution.reject_attribution",
            version="v1",
            surface=WidgetSurface.RESEARCH,
            question="Which A-share constraints prevent target orders from becoming fills?",
            evidence_types=("ashare_portfolio_validation", "ashare_execution_ledger"),
            data_endpoint="/api/v1/a4/{validation_id}/execution/rejections",
            data_schema="finagent.visualization.a4-rejection-attribution.v1",
            renderer=WidgetRenderer.BAR,
            parameters=_parameters("validation_id", "fold_id", "date_range"),
            link_keys=("validation_id", "fold_id", "date_range"),
            lineage_refs=("validation_id",),
        ),
        FinWidgetSpec(
            widget_id="governance.lineage",
            version="v1",
            surface=WidgetSurface.RESEARCH,
            question="Which immutable evidence objects produced the selected result?",
            evidence_types=(
                "ashare_factor_research_acceptance",
                "ashare_robust_research_program",
                "ashare_portfolio_validation",
            ),
            data_endpoint="/api/v1/evidence/{evidence_id}/lineage",
            data_schema="finagent.visualization.lineage-graph.v1",
            renderer=WidgetRenderer.DAG,
            parameters=_parameters("evidence_id"),
            link_keys=("evidence_id",),
            lineage_refs=("evidence_id",),
        ),
        FinWidgetSpec(
            widget_id="agent.run.activity",
            version="v1",
            surface=WidgetSurface.AGENT,
            question="What governed actions did the Agent perform and what evidence did they produce?",
            evidence_types=("agent_run",),
            data_endpoint="/api/v1/agent/runs/{run_id}",
            data_schema="finagent.visualization.agent-run-projection.v1",
            renderer=WidgetRenderer.TIMELINE,
            parameters=_parameters("run_id"),
            link_keys=("run_id",),
            lineage_refs=("run_id",),
        ),
    )
    ids = {value.widget_id for value in values}
    if len(ids) != len(values):
        raise EvidenceContractError("default widget ids must be unique")
    return values
