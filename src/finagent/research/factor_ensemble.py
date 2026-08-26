from __future__ import annotations

from collections.abc import Sequence

from finagent.agents.generated_features import GeneratedFeatureArtifact
from finagent.models.alpha import GeneratedFeatureEnsembleAlphaModel
from finagent.sandbox import LocalFeatureSandbox

from .factor_quant import FactorEnsembleSelection, FactorQuantFamilyReport


class FactorEnsembleModelBuilder:
    """Resolve a frozen quantitative factor selection into a standard AlphaModel.

    The builder is intentionally thin: it does not re-rank factors or recompute
    weights.  It verifies that the selection belongs to the supplied factor-quant
    report, that the full candidate denominator matches the report, and then resolves
    selected digests to immutable ``GeneratedFeatureArtifact`` objects in selection
    order.
    """

    VERSION = "factor-ensemble-model-builder-v1"

    def build(
        self,
        *,
        report: FactorQuantFamilyReport,
        selection: FactorEnsembleSelection,
        candidates: Sequence[GeneratedFeatureArtifact],
        ridge: float = 1e-8,
        min_observations: int = 30,
        sandbox: LocalFeatureSandbox | None = None,
        batch_size: int = 128,
    ) -> GeneratedFeatureEnsembleAlphaModel:
        artifacts = tuple(candidates)
        if not artifacts:
            raise ValueError("factor ensemble builder requires candidates")
        if len({artifact.digest for artifact in artifacts}) != len(artifacts):
            raise ValueError("factor ensemble builder received duplicate candidate digests")
        if len({artifact.spec.feature_id for artifact in artifacts}) != len(artifacts):
            raise ValueError("factor ensemble builder received duplicate feature ids")
        if selection.report_id != report.report_id:
            raise ValueError("factor ensemble selection does not belong to factor quant report")
        if selection.primary_label != report.primary_label:
            raise ValueError("factor ensemble selection label does not match factor quant report")

        report_digests = {candidate.feature_digest for candidate in report.candidates}
        artifact_digests = {artifact.digest for artifact in artifacts}
        if artifact_digests != report_digests:
            missing = sorted(report_digests - artifact_digests)
            extra = sorted(artifact_digests - report_digests)
            raise ValueError(
                "factor ensemble candidate denominator does not match report; "
                f"missing={missing}, extra={extra}"
            )

        by_digest = {artifact.digest: artifact for artifact in artifacts}
        selected = tuple(by_digest[digest] for digest in selection.feature_digests)
        return GeneratedFeatureEnsembleAlphaModel(
            selected,
            selection.weights,
            label_name=selection.primary_label,
            ridge=ridge,
            min_observations=min_observations,
            sandbox=sandbox,
            batch_size=batch_size,
        )
