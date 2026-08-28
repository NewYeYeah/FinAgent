from __future__ import annotations

import numpy as np

from finagent.agents.generated_features import GeneratedFeatureArtifact
from finagent.domain.experiments import ArtifactRef, ArtifactType
from finagent.domain.research import DatasetRequest, ResearchDataset, ResearchSplit
from finagent.runtime import AutoParallelPolicy
from finagent.sandbox import FeatureSandboxRequest, LocalFeatureSandbox

from .generated_feature_eval import GeneratedFeatureMaterializer


class PanelGeneratedFeatureMaterializer(GeneratedFeatureMaterializer):
    """Materialize generated factors from an already batched PIT panel.

    The generic materializer asks an adapter for one feature window per asset/session.
    That is appropriate for small remote datasets but becomes prohibitively expensive
    for a DuckDB-backed A-share panel. This implementation builds each raw input panel
    once per candidate and slices causal rolling windows in memory before sandbox
    evaluation. It preserves the same generated-feature and universe contracts.
    """

    VERSION = "panel-generated-feature-materializer-v1"

    def __init__(
        self,
        adapter,
        *,
        sandbox: LocalFeatureSandbox | None = None,
        universe_provider=None,
        batch_size: int = 512,
        parallel_policy: AutoParallelPolicy | None = None,
    ) -> None:
        super().__init__(
            adapter,
            sandbox=sandbox,
            universe_provider=universe_provider,
            batch_size=batch_size,
            parallel_policy=parallel_policy,
        )

    def materialize(
        self,
        artifact: GeneratedFeatureArtifact,
        request: DatasetRequest,
    ) -> ResearchDataset:
        raw_request = DatasetRequest(
            universe=request.universe,
            features=artifact.spec.input_fields,
            labels=request.labels,
            splits=request.splits,
            dataset_id=f"{request.dataset_id}-raw",
            metadata={
                **dict(request.metadata),
                "generated_feature_raw": artifact.digest,
                "materializer_version": self.VERSION,
            },
        )
        raw = self.adapter.build_dataset(raw_request)
        panels: dict[str, ResearchSplit] = {}
        output_name = f"generated:{artifact.spec.feature_id}"

        for split_name in request.splits:
            raw_panel = raw.get_split(split_name)
            values = np.full((raw_panel.n_times, raw_panel.n_assets, 1), np.nan, dtype=float)
            eligibility = np.array(raw_panel.eligibility_mask, dtype=bool, copy=True)
            if self.universe_provider is not None:
                for time_index, timestamp in enumerate(raw_panel.timestamps):
                    snapshot = self.universe_provider.snapshot(timestamp, raw_panel.assets)
                    eligibility[time_index] &= snapshot.mask(raw_panel.assets)

            jobs: list[tuple[int, int, FeatureSandboxRequest]] = []
            field_indices = {
                name: raw_panel.feature_index(name) for name in artifact.spec.input_fields
            }
            lookback = artifact.spec.lookback
            for time_index in range(raw_panel.n_times):
                start = time_index - lookback + 1
                if start < 0:
                    continue
                for asset_index in range(raw_panel.n_assets):
                    if not eligibility[time_index, asset_index]:
                        continue
                    inputs: dict[str, list[float | None]] = {}
                    has_missing = False
                    for field_name, feature_index in field_indices.items():
                        series = raw_panel.feature_values[
                            start : time_index + 1,
                            asset_index,
                            feature_index,
                        ]
                        converted = [
                            float(value) if np.isfinite(value) else None for value in series
                        ]
                        if any(value is None for value in converted):
                            has_missing = True
                            break
                        inputs[field_name] = converted
                    if has_missing:
                        continue
                    jobs.append(
                        (
                            time_index,
                            asset_index,
                            FeatureSandboxRequest(artifact.spec, artifact.source, inputs),
                        )
                    )
            self._run_jobs(jobs, values)
            panels[split_name] = ResearchSplit(
                timestamps=raw_panel.timestamps,
                assets=raw_panel.assets,
                feature_names=(output_name,),
                label_names=raw_panel.label_names,
                feature_values=values,
                label_values=raw_panel.label_values,
                metadata={
                    **dict(raw_panel.metadata),
                    "generated_feature_digest": artifact.digest,
                    "materializer_version": self.VERSION,
                    "window_source": "materialized_panel",
                    "universe_version": (
                        self.universe_provider.data_version
                        if self.universe_provider is not None
                        else raw_panel.metadata.get("universe_version", "static/default")
                    ),
                },
                eligibility_mask=eligibility,
            )

        digest = self._digest(artifact, raw.artifact, panels)
        materialized_artifact = ArtifactRef(
            artifact_id=request.dataset_id,
            artifact_type=ArtifactType.DATASET,
            version=self.VERSION,
            digest=digest,
            uri=f"generated-dataset://{artifact.spec.feature_id}/{digest}",
        )
        return ResearchDataset(
            artifact=materialized_artifact,
            universe=request.universe,
            features=(output_name,),
            labels=request.labels,
            splits=request.splits,
            point_in_time=True,
            metadata={
                **dict(request.metadata),
                "source_dataset_digest": raw.artifact.digest,
                "generated_feature_digest": artifact.digest,
                "generated_feature_code_digest": artifact.validation.source_digest,
                "materializer_version": self.VERSION,
                "window_source": "materialized_panel",
            },
            panels=panels,
        )
