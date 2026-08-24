from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

from finagent.domain._validation import require_non_empty
from finagent.domain.assets import AssetId
from finagent.domain.experiments import ArtifactRef

from ..planning import ExperimentVariant


def _artifact_payload(ref: ArtifactRef) -> dict[str, object]:
    return {
        "artifact_id": ref.artifact_id,
        "artifact_type": ref.artifact_type.value,
        "version": ref.version,
        "digest": ref.digest,
        "uri": ref.uri,
    }


def _asset_payload(asset: AssetId) -> dict[str, str]:
    return {
        "symbol": asset.symbol,
        "asset_type": asset.asset_type.value,
        "venue": asset.venue,
        "currency": asset.currency,
    }


@dataclass(frozen=True, slots=True)
class ExperimentTemplate:
    template_id: str
    evaluator_id: str
    dataset: ArtifactRef
    code: ArtifactRef
    universe: tuple[AssetId, ...]
    parameter_names: frozenset[str]
    seed: int = 0
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "template_id", require_non_empty(self.template_id, "template_id"))
        object.__setattr__(self, "evaluator_id", require_non_empty(self.evaluator_id, "evaluator_id"))
        if not self.universe:
            raise ValueError("ExperimentTemplate universe cannot be empty")
        object.__setattr__(self, "parameter_names", frozenset(require_non_empty(name, "parameter name") for name in self.parameter_names))
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise TypeError("seed must be an int")
        object.__setattr__(self, "metadata", MappingProxyType({str(k): str(v) for k, v in self.metadata.items()}))

    def materialize(self, *, family_id: str, variant: ExperimentVariant) -> dict[str, object]:
        provided = set(variant.parameters)
        allowed = set(self.parameter_names)
        if provided - allowed:
            raise ValueError(f"variant contains parameters outside template allowlist: {sorted(provided - allowed)}")
        if allowed - provided:
            raise ValueError(f"variant is missing template parameters: {sorted(allowed - provided)}")
        metadata = dict(self.metadata)
        metadata.update({"template_id": self.template_id, "variant_id": variant.variant_id})
        return {
            "family_id": family_id,
            "experiment_id": variant.experiment_id,
            "hypothesis": variant.hypothesis,
            "dataset": _artifact_payload(self.dataset),
            "code": _artifact_payload(self.code),
            "universe": [_asset_payload(asset) for asset in self.universe],
            "evaluator_id": self.evaluator_id,
            "parameters": dict(variant.parameters),
            "seed": self.seed,
            "metadata": metadata,
            "role": "variant",
        }


class ExperimentTemplateRegistry:
    def __init__(self) -> None:
        self._templates: dict[str, ExperimentTemplate] = {}

    def register(self, template: ExperimentTemplate) -> None:
        if template.template_id in self._templates:
            raise ValueError(f"template {template.template_id!r} is already registered")
        self._templates[template.template_id] = template

    def get(self, template_id: str) -> ExperimentTemplate:
        try:
            return self._templates[template_id]
        except KeyError as exc:
            raise KeyError(f"unregistered experiment template {template_id!r}") from exc

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._templates))
