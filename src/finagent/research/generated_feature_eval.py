from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Mapping, Sequence

import numpy as np
from scipy.stats import rankdata, t as student_t

from finagent.agents.generated_features import GeneratedFeatureArtifact, SQLiteGeneratedFeatureStore
from finagent.domain.assets import AssetId
from finagent.domain.experiments import ArtifactRef, ArtifactType, ExperimentSpec
from finagent.domain.research import DatasetRequest, ResearchDataset, ResearchSplit
from finagent.domain.trading import TradeActivity
from finagent.domain.universe import UniverseProvider
from finagent.sandbox import FeatureSandboxRequest, LocalFeatureSandbox

from .runner import ExperimentEvaluation


@dataclass(frozen=True, slots=True)
class GeneratedFeatureEvaluationConfig:
    label_name: str = "forward_simple_return_1"
    split_name: str = "test"
    transaction_cost_bps: float = 5.0
    annualization: int = 252
    min_cross_section: int = 2
    min_periods: int = 5
    fail_on_missing_realized_return: bool = True

    def __post_init__(self) -> None:
        if self.transaction_cost_bps < 0:
            raise ValueError("transaction_cost_bps must be >= 0")
        if self.annualization < 1:
            raise ValueError("annualization must be >= 1")
        if self.min_cross_section < 2:
            raise ValueError("min_cross_section must be >= 2")
        if self.min_periods < 2:
            raise ValueError("min_periods must be >= 2")


@dataclass(frozen=True, slots=True)
class GeneratedFeatureResearchTrace:
    feature_digest: str
    dataset_digest: str
    split_name: str
    timestamps: tuple[datetime, ...]
    gross_returns: tuple[float, ...]
    net_returns: tuple[float, ...]
    information_coefficients: tuple[float, ...]
    turnovers: tuple[float, ...]
    metrics: Mapping[str, float]
    pvalue: float

    def __post_init__(self) -> None:
        sizes = {
            len(self.timestamps),
            len(self.gross_returns),
            len(self.net_returns),
            len(self.turnovers),
        }
        if len(sizes) != 1:
            raise ValueError("trace timestamps/returns/turnovers must have equal length")
        object.__setattr__(
            self,
            "metrics",
            MappingProxyType({str(k): float(v) for k, v in self.metrics.items()}),
        )


@dataclass(frozen=True, slots=True)
class NestedGeneratedFeatureFoldResult:
    outer_fold_index: int
    inner_validation: tuple[GeneratedFeatureResearchTrace, ...]
    outer_test: GeneratedFeatureResearchTrace


@dataclass(frozen=True, slots=True)
class NestedGeneratedFeatureStudyResult:
    feature_digest: str
    folds: tuple[NestedGeneratedFeatureFoldResult, ...]

    @property
    def outer_net_returns(self) -> tuple[float, ...]:
        return tuple(value for fold in self.folds for value in fold.outer_test.net_returns)


class GeneratedFeatureMaterializer:
    """Materialize generated code against PIT adapter windows and PIT eligibility.

    Feature windows are built at each row ``asof``. An optional ``UniverseProvider``
    independently supplies formation eligibility at the same ``asof``. Forward-label
    availability is never consulted when deciding which assets receive a feature or
    can later receive a portfolio weight.

    The local sandbox supports independent PIT-window batches. Batching only reduces
    process-launch overhead; each generated function invocation receives one historical
    window and cannot inspect another asset/time window.
    """

    VERSION = "generated-feature-materializer-v2"

    def __init__(
        self,
        adapter,
        *,
        sandbox: LocalFeatureSandbox | None = None,
        universe_provider: UniverseProvider | None = None,
        batch_size: int = 128,
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be >= 1")
        self.adapter = adapter
        self.sandbox = sandbox or LocalFeatureSandbox()
        self.universe_provider = universe_provider
        self.batch_size = batch_size

    def _run_jobs(
        self,
        jobs: list[tuple[int, int, FeatureSandboxRequest]],
        values: np.ndarray,
    ) -> None:
        run_batch = getattr(self.sandbox, "run_batch", None)
        if callable(run_batch):
            for start in range(0, len(jobs), self.batch_size):
                chunk = jobs[start : start + self.batch_size]
                results = run_batch(tuple(job[2] for job in chunk))
                if len(results) != len(chunk):
                    raise RuntimeError("sandbox batch result count does not match request count")
                for (time_index, asset_index, _), result in zip(chunk, results):
                    last = result.values[-1]
                    if last is not None:
                        values[time_index, asset_index, 0] = float(last)
            return
        for time_index, asset_index, request in jobs:
            result = self.sandbox.run(request)
            last = result.values[-1]
            if last is not None:
                values[time_index, asset_index, 0] = float(last)

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
            metadata={**dict(request.metadata), "generated_feature_raw": artifact.digest},
        )
        raw = self.adapter.build_dataset(raw_request)
        panels: dict[str, ResearchSplit] = {}
        output_name = f"generated:{artifact.spec.feature_id}"

        for split_name in request.splits:
            raw_panel = raw.get_split(split_name)
            values = np.full((raw_panel.n_times, raw_panel.n_assets, 1), np.nan, dtype=float)
            eligibility = np.array(raw_panel.eligibility_mask, dtype=bool, copy=True)
            jobs: list[tuple[int, int, FeatureSandboxRequest]] = []

            for time_index, timestamp in enumerate(raw_panel.timestamps):
                if self.universe_provider is not None:
                    snapshot = self.universe_provider.snapshot(timestamp, raw_panel.assets)
                    eligibility[time_index] &= snapshot.mask(raw_panel.assets)
                for asset_index, asset in enumerate(raw_panel.assets):
                    if not eligibility[time_index, asset_index]:
                        continue
                    try:
                        window = self.adapter.feature_window(
                            timestamp,
                            (asset,),
                            artifact.spec.input_fields,
                            artifact.spec.lookback,
                        )
                    except (KeyError, ValueError):
                        continue
                    if window.lookback < artifact.spec.lookback:
                        continue
                    inputs: dict[str, list[float | None]] = {}
                    has_missing = False
                    for field_name in artifact.spec.input_fields:
                        series = window.asset_feature(asset, field_name)
                        converted = [None if not np.isfinite(v) else float(v) for v in series]
                        has_missing = has_missing or any(value is None for value in converted)
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
            },
            panels=panels,
        )

    @classmethod
    def _digest(
        cls,
        artifact: GeneratedFeatureArtifact,
        raw_artifact: ArtifactRef,
        panels: Mapping[str, ResearchSplit],
    ) -> str:
        digest = hashlib.sha256()
        manifest = {
            "materializer_version": cls.VERSION,
            "feature_digest": artifact.digest,
            "raw_dataset_digest": raw_artifact.digest,
        }
        digest.update(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode())
        for split_name in sorted(panels):
            panel = panels[split_name]
            digest.update(split_name.encode())
            digest.update("|".join(ts.isoformat() for ts in panel.timestamps).encode())
            digest.update(panel.feature_values.tobytes(order="C"))
            digest.update(panel.label_values.tobytes(order="C"))
            digest.update(panel.eligibility_mask.tobytes(order="C"))
        return digest.hexdigest()


def _weights_from_feature(values: np.ndarray, formation_mask: np.ndarray) -> np.ndarray:
    weights = np.zeros_like(values, dtype=float)
    chosen = values[formation_mask]
    if chosen.size < 2 or np.allclose(chosen, chosen[0]):
        return weights
    ranks = rankdata(chosen, method="average")
    centered = ranks - ranks.mean()
    gross = np.abs(centered).sum()
    if gross <= 0:
        return weights
    weights[formation_mask] = centered / gross
    return weights


def _one_sided_mean_pvalue(values: Sequence[float]) -> float:
    array = np.asarray(values, dtype=float)
    if array.size < 2:
        return 1.0
    std = float(np.std(array, ddof=1))
    mean = float(np.mean(array))
    if std <= 1e-15:
        return 0.0 if mean > 0 else 1.0
    statistic = mean / (std / math.sqrt(array.size))
    return float(student_t.sf(statistic, df=array.size - 1))


def evaluate_generated_feature_dataset(
    dataset: ResearchDataset,
    *,
    feature_digest: str,
    config: GeneratedFeatureEvaluationConfig = GeneratedFeatureEvaluationConfig(),
) -> GeneratedFeatureResearchTrace:
    split = dataset.get_split(config.split_name)
    if len(split.feature_names) != 1:
        raise ValueError("generated feature evaluator requires exactly one feature column")
    if config.label_name not in split.label_names:
        raise KeyError(f"label {config.label_name!r} not found in split")
    feature = split.feature_values[:, :, 0]
    labels = split.label_panel(config.label_name)
    previous_weights = np.zeros(split.n_assets, dtype=float)
    gross_returns: list[float] = []
    net_returns: list[float] = []
    turnovers: list[float] = []
    gross_traded_weights: list[float] = []
    timestamps: list[datetime] = []
    ics: list[float] = []
    valid_feature_cells = 0
    eligible_cells = 0
    unrealized_boundary_periods = 0

    for row, timestamp in enumerate(split.timestamps):
        f = feature[row]
        y = labels[row]
        eligible = np.asarray(split.eligibility_at(row), dtype=bool)
        formation = eligible & np.isfinite(f)
        eligible_cells += int(eligible.sum())
        valid_feature_cells += int(formation.sum())
        if int(formation.sum()) < config.min_cross_section:
            continue

        realized_formation = formation & np.isfinite(y)
        if not np.any(realized_formation):
            # A completely unrealized formation cross-section is a horizon boundary:
            # the return target has not matured yet. It is omitted from realized
            # performance without changing the PIT formation universe or charging a
            # fictitious close/reopen turnover. Partial missingness is handled below
            # and still fails closed by default.
            unrealized_boundary_periods += 1
            continue

        # IC is an ex-post statistic, so missing realised labels may be excluded from
        # the *IC calculation* only. They may never alter the already-formed weights.
        ic_mask = realized_formation
        if int(ic_mask.sum()) >= config.min_cross_section:
            fv = f[ic_mask]
            yv = y[ic_mask]
            if not np.allclose(fv, fv[0]) and not np.allclose(yv, yv[0]):
                ics.append(float(np.corrcoef(rankdata(fv), rankdata(yv))[0, 1]))

        weights = _weights_from_feature(f, formation)
        if np.abs(weights).sum() <= 0:
            continue
        active = np.abs(weights) > 1e-15
        missing_active = active & ~np.isfinite(y)
        if np.any(missing_active):
            missing_assets = [split.assets[i].key for i in np.flatnonzero(missing_active)]
            if config.fail_on_missing_realized_return:
                raise ValueError(
                    "formed portfolio has missing realized forward return for assets "
                    f"{missing_assets}; provide delisting/corporate-action return semantics "
                    "or mark the asset ineligible using PIT information before formation"
                )

        gross_return = float(np.dot(weights, np.where(np.isfinite(y), y, 0.0)))
        activity = TradeActivity.from_weights(previous_weights, weights)
        cost = activity.linear_cost_fraction(config.transaction_cost_bps)
        net_return = gross_return - cost
        timestamps.append(timestamp)
        gross_returns.append(gross_return)
        net_returns.append(net_return)
        turnovers.append(activity.one_way_turnover)
        gross_traded_weights.append(activity.gross_traded_weight)
        previous_weights = weights

    if len(net_returns) < config.min_periods:
        raise ValueError(
            f"generated feature produced only {len(net_returns)} evaluable periods; "
            f"minimum is {config.min_periods}"
        )
    net = np.asarray(net_returns, dtype=float)
    gross = np.asarray(gross_returns, dtype=float)
    turnover_array = np.asarray(turnovers, dtype=float)
    gross_trade_array = np.asarray(gross_traded_weights, dtype=float)
    ic_array = np.asarray(ics, dtype=float)
    mean_ic = float(np.mean(ic_array)) if ic_array.size else 0.0
    ic_std = float(np.std(ic_array, ddof=1)) if ic_array.size > 1 else 0.0
    icir = mean_ic / ic_std if ic_std > 1e-15 else 0.0
    net_std = float(np.std(net, ddof=1))
    net_sharpe = (
        float(np.mean(net) / net_std * math.sqrt(config.annualization))
        if net_std > 1e-15
        else 0.0
    )
    metrics = {
        "mean_ic": mean_ic,
        "icir": icir,
        "annualized_icir": icir * math.sqrt(config.annualization),
        "mean_gross_return": float(np.mean(gross)),
        "mean_net_return": float(np.mean(net)),
        "gross_cumulative_return": float(np.prod(1.0 + gross) - 1.0),
        "net_cumulative_return": float(np.prod(1.0 + net) - 1.0),
        "net_sharpe": net_sharpe,
        # Backward-compatible name: this is explicitly one-way turnover.
        "mean_turnover": float(np.mean(turnover_array)),
        "mean_one_way_turnover": float(np.mean(turnover_array)),
        "mean_gross_traded_weight": float(np.mean(gross_trade_array)),
        "transaction_cost_bps": float(config.transaction_cost_bps),
        "coverage": float(valid_feature_cells / eligible_cells) if eligible_cells else 0.0,
        "evaluated_periods": float(len(net_returns)),
        "ic_periods": float(len(ics)),
        "unrealized_boundary_periods": float(unrealized_boundary_periods),
    }
    return GeneratedFeatureResearchTrace(
        feature_digest=feature_digest,
        dataset_digest=dataset.artifact.digest,
        split_name=config.split_name,
        timestamps=tuple(timestamps),
        gross_returns=tuple(gross_returns),
        net_returns=tuple(net_returns),
        information_coefficients=tuple(ics),
        turnovers=tuple(turnovers),
        metrics=metrics,
        pvalue=_one_sided_mean_pvalue(net_returns),
    )


class SQLiteGeneratedFeatureResearchStore:
    """Immutable numerical evidence used by family-level validation providers."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS generated_feature_research (
                    experiment_id TEXT PRIMARY KEY,
                    feature_digest TEXT NOT NULL,
                    dataset_digest TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
            """)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def register(self, experiment_id: str, trace: GeneratedFeatureResearchTrace) -> None:
        payload = {
            "split_name": trace.split_name,
            "timestamps": [ts.isoformat() for ts in trace.timestamps],
            "gross_returns": list(trace.gross_returns),
            "net_returns": list(trace.net_returns),
            "information_coefficients": list(trace.information_coefficients),
            "turnovers": list(trace.turnovers),
            "metrics": dict(trace.metrics),
            "pvalue": trace.pvalue,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
        with self._connect() as con:
            existing = con.execute(
                "SELECT feature_digest, dataset_digest, payload_json "
                "FROM generated_feature_research WHERE experiment_id=?",
                (experiment_id,),
            ).fetchone()
            candidate = (trace.feature_digest, trace.dataset_digest, encoded)
            if existing is not None:
                if tuple(existing) != candidate:
                    raise ValueError(f"research evidence for {experiment_id!r} is immutable")
                return
            con.execute(
                "INSERT INTO generated_feature_research VALUES (?, ?, ?, ?)",
                (experiment_id, trace.feature_digest, trace.dataset_digest, encoded),
            )

    def get(self, experiment_id: str) -> GeneratedFeatureResearchTrace:
        with self._connect() as con:
            row = con.execute(
                "SELECT feature_digest, dataset_digest, payload_json "
                "FROM generated_feature_research WHERE experiment_id=?",
                (experiment_id,),
            ).fetchone()
        if row is None:
            raise KeyError(experiment_id)
        payload = json.loads(row[2])
        return GeneratedFeatureResearchTrace(
            feature_digest=row[0],
            dataset_digest=row[1],
            split_name=payload["split_name"],
            timestamps=tuple(datetime.fromisoformat(v) for v in payload["timestamps"]),
            gross_returns=tuple(float(v) for v in payload["gross_returns"]),
            net_returns=tuple(float(v) for v in payload["net_returns"]),
            information_coefficients=tuple(float(v) for v in payload["information_coefficients"]),
            turnovers=tuple(float(v) for v in payload["turnovers"]),
            metrics=payload["metrics"],
            pvalue=float(payload["pvalue"]),
        )


class GeneratedFeatureEvaluator:
    """Approved evaluator backed by PIT materialization and real return evidence."""

    def __init__(
        self,
        *,
        adapter,
        feature_store: SQLiteGeneratedFeatureStore,
        dataset_request: DatasetRequest,
        research_store: SQLiteGeneratedFeatureResearchStore | None = None,
        sandbox: LocalFeatureSandbox | None = None,
        universe_provider: UniverseProvider | None = None,
        config: GeneratedFeatureEvaluationConfig = GeneratedFeatureEvaluationConfig(),
    ) -> None:
        self.feature_store = feature_store
        self.dataset_request = dataset_request
        self.research_store = research_store
        self.config = config
        self.materializer = GeneratedFeatureMaterializer(
            adapter,
            sandbox=sandbox,
            universe_provider=universe_provider,
        )

    def __call__(self, spec: ExperimentSpec) -> ExperimentEvaluation:
        digest = str(spec.metadata.get("generated_feature_digest", "")).strip() or spec.code.digest
        artifact = self.feature_store.get(digest)
        if artifact.digest != spec.code.digest:
            raise ValueError("experiment code digest does not match generated feature artifact")
        dataset = self.materializer.materialize(artifact, self.dataset_request)
        trace = evaluate_generated_feature_dataset(
            dataset,
            feature_digest=artifact.digest,
            config=self.config,
        )
        if self.research_store is not None:
            self.research_store.register(spec.experiment_id, trace)
        return ExperimentEvaluation(
            metrics={**dict(trace.metrics), "one_sided_net_return_pvalue": trace.pvalue},
            passed=True,
            produced_artifacts=(artifact.factor_artifact_ref(), dataset.artifact),
            notes=(
                f"generated feature {artifact.spec.feature_id}; split={self.config.split_name}; "
                "passed denotes successful governed evaluation, not statistical promotion"
            ),
        )


class GeneratedFeatureFamilyValidationInputProvider:
    """Bridge stored real return traces into the existing family validator."""

    def __init__(self, registry, research_store: SQLiteGeneratedFeatureResearchStore) -> None:
        self.registry = registry
        self.research_store = research_store

    def __call__(self, family_id: str):
        from finagent.agents.tools import FamilyValidationInputs

        members = self.registry.family_members(family_id)
        returns: dict[str, tuple[float, ...]] = {}
        pvalues: dict[str, float] = {}
        for member in members:
            trace = self.research_store.get(member.experiment_id)
            returns[member.experiment_id] = trace.net_returns
            pvalues[member.experiment_id] = trace.pvalue
        return FamilyValidationInputs(trial_returns=returns, pvalues=pvalues)


class GeneratedFeatureNestedWalkForwardStudy:
    """Evaluate one feature through existing nested purged walk-forward folds."""

    def __init__(
        self,
        *,
        adapter,
        splitter,
        sandbox: LocalFeatureSandbox | None = None,
        universe_provider: UniverseProvider | None = None,
        config: GeneratedFeatureEvaluationConfig = GeneratedFeatureEvaluationConfig(),
    ) -> None:
        self.adapter = adapter
        self.splitter = splitter
        self.materializer = GeneratedFeatureMaterializer(
            adapter,
            sandbox=sandbox,
            universe_provider=universe_provider,
        )
        self.config = config

    def run(
        self,
        artifact: GeneratedFeatureArtifact,
        *,
        universe: tuple[AssetId, ...],
        start: datetime,
        end: datetime,
        dataset_id_prefix: str = "generated-feature-nested",
    ) -> NestedGeneratedFeatureStudyResult:
        calendar = self.adapter.calendar(start, end, universe)
        nested = self.splitter.split(calendar, labels=(self.config.label_name,))
        fold_results: list[NestedGeneratedFeatureFoldResult] = []
        for nested_fold in nested:
            outer = nested_fold.outer_fold
            inner_traces: list[GeneratedFeatureResearchTrace] = []
            for inner in nested_fold.inner_folds:
                request = DatasetRequest(
                    universe=universe,
                    features=artifact.spec.input_fields,
                    labels=(self.config.label_name,),
                    splits={"train": inner.train, "validation": inner.test},
                    dataset_id=(
                        f"{dataset_id_prefix}-outer-{outer.fold_index:03d}-"
                        f"inner-{inner.fold_index:03d}"
                    ),
                    metadata={"nested_role": "inner"},
                )
                dataset = self.materializer.materialize(artifact, request)
                inner_config = GeneratedFeatureEvaluationConfig(
                    label_name=self.config.label_name,
                    split_name="validation",
                    transaction_cost_bps=self.config.transaction_cost_bps,
                    annualization=self.config.annualization,
                    min_cross_section=self.config.min_cross_section,
                    min_periods=self.config.min_periods,
                    fail_on_missing_realized_return=self.config.fail_on_missing_realized_return,
                )
                inner_traces.append(
                    evaluate_generated_feature_dataset(
                        dataset,
                        feature_digest=artifact.digest,
                        config=inner_config,
                    )
                )
            outer_request = DatasetRequest(
                universe=universe,
                features=artifact.spec.input_fields,
                labels=(self.config.label_name,),
                splits={"train": outer.train, "test": outer.test},
                dataset_id=f"{dataset_id_prefix}-outer-{outer.fold_index:03d}",
                metadata={"nested_role": "outer"},
            )
            outer_dataset = self.materializer.materialize(artifact, outer_request)
            outer_config = GeneratedFeatureEvaluationConfig(
                label_name=self.config.label_name,
                split_name="test",
                transaction_cost_bps=self.config.transaction_cost_bps,
                annualization=self.config.annualization,
                min_cross_section=self.config.min_cross_section,
                min_periods=self.config.min_periods,
                fail_on_missing_realized_return=self.config.fail_on_missing_realized_return,
            )
            outer_trace = evaluate_generated_feature_dataset(
                outer_dataset,
                feature_digest=artifact.digest,
                config=outer_config,
            )
            fold_results.append(
                NestedGeneratedFeatureFoldResult(
                    outer.fold_index,
                    tuple(inner_traces),
                    outer_trace,
                )
            )
        return NestedGeneratedFeatureStudyResult(artifact.digest, tuple(fold_results))
