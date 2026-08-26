from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Protocol

import numpy as np
from scipy.stats import t as student_t

from finagent.agents.domain import AgentTask
from finagent.agents.generated_features import GeneratedFeatureArtifact
from finagent.agents.llm_feature import LLMFeatureGenerator
from finagent.backtest.market_study import MarketStudyConfig
from finagent.backtest.timed import TimedBacktestConfig, TimedEventDrivenBacktestEngine
from finagent.data.ingestion.provider import ProviderCapabilities, ResearchDataRequirement
from finagent.domain.assets import AssetId, AssetType
from finagent.domain.research import DatasetRequest
from finagent.models.alpha import GeneratedFeatureAlphaModel
from finagent.models.risk import GARCH11RiskModel
from finagent.portfolio import MeanVarianceConfig, MeanVarianceOptimizer
from finagent.research.generated_feature_eval import (
    GeneratedFeatureEvaluationConfig,
    GeneratedFeatureNestedWalkForwardStudy,
    GeneratedFeatureResearchTrace,
)
from finagent.research.programs import SQLiteResearchProgramStore
from finagent.services import StaticRiskGate, TimedSimulatedExchange


@dataclass(frozen=True, slots=True)
class AgentMarketResearchConfig:
    max_candidates: int = 8
    family_alpha: float = 0.05
    selection_metric: str = "net_sharpe"
    label_name: str = "forward_simple_return_1"
    transaction_cost_bps: float = 5.0
    min_cross_section: int = 2
    min_periods: int = 5
    require_statistical_acceptance: bool = False
    market: MarketStudyConfig = field(default_factory=MarketStudyConfig)

    def __post_init__(self) -> None:
        if self.max_candidates < 1:
            raise ValueError("max_candidates must be >= 1")
        if not 0.0 < self.family_alpha < 1.0:
            raise ValueError("family_alpha must be in (0, 1)")
        if not self.selection_metric.strip() or not self.label_name.strip():
            raise ValueError("selection_metric and label_name must be non-empty")
        if self.transaction_cost_bps < 0:
            raise ValueError("transaction_cost_bps must be >= 0")
        if self.min_cross_section < 2 or self.min_periods < 2:
            raise ValueError("min_cross_section/min_periods are too small")


@dataclass(frozen=True, slots=True)
class AgentMarketCandidate:
    feature_id: str
    feature_digest: str
    hypothesis: str
    description: str
    lookback: int
    input_fields: tuple[str, ...]

    @classmethod
    def from_artifact(cls, artifact: GeneratedFeatureArtifact) -> AgentMarketCandidate:
        return cls(
            feature_id=artifact.spec.feature_id,
            feature_digest=artifact.digest,
            hypothesis=artifact.spec.hypothesis,
            description=artifact.spec.description,
            lookback=artifact.spec.lookback,
            input_fields=artifact.spec.input_fields,
        )


@dataclass(frozen=True, slots=True)
class AgentMarketFoldResult:
    outer_fold_index: int
    selected_feature_id: str
    selected_feature_digest: str
    statistically_accepted: bool
    inner_mean_scores: Mapping[str, float]
    inner_raw_pvalues: Mapping[str, float]
    inner_adjusted_pvalues: Mapping[str, float]
    signal_outer_metrics: Mapping[str, float]
    portfolio_outer_metrics: Mapping[str, float]
    outer_start: str
    outer_end: str

    def __post_init__(self) -> None:
        for name in (
            "inner_mean_scores",
            "inner_raw_pvalues",
            "inner_adjusted_pvalues",
            "signal_outer_metrics",
            "portfolio_outer_metrics",
        ):
            object.__setattr__(
                self,
                name,
                MappingProxyType({str(k): float(v) for k, v in getattr(self, name).items()}),
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "outer_fold_index": self.outer_fold_index,
            "selected_feature_id": self.selected_feature_id,
            "selected_feature_digest": self.selected_feature_digest,
            "statistically_accepted": self.statistically_accepted,
            "inner_mean_scores": dict(self.inner_mean_scores),
            "inner_raw_pvalues": dict(self.inner_raw_pvalues),
            "inner_adjusted_pvalues": dict(self.inner_adjusted_pvalues),
            "signal_outer_metrics": dict(self.signal_outer_metrics),
            "portfolio_outer_metrics": dict(self.portfolio_outer_metrics),
            "outer_start": self.outer_start,
            "outer_end": self.outer_end,
        }


@dataclass(frozen=True, slots=True)
class AgentMarketResearchResult:
    study_id: str
    task_id: str
    program_id: str
    family_id: str
    provider: str
    data_version: str
    universe: tuple[str, ...]
    candidates: tuple[AgentMarketCandidate, ...]
    folds: tuple[AgentMarketFoldResult, ...]
    aggregate_portfolio_metrics: Mapping[str, float]
    promotion_eligible_folds: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "aggregate_portfolio_metrics",
            MappingProxyType(
                {str(k): float(v) for k, v in self.aggregate_portfolio_metrics.items()}
            ),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "finagent.agent-market-research.v1",
            "study_id": self.study_id,
            "task_id": self.task_id,
            "program_id": self.program_id,
            "family_id": self.family_id,
            "provider": self.provider,
            "data_version": self.data_version,
            "universe": list(self.universe),
            "candidates": [asdict(candidate) for candidate in self.candidates],
            "folds": [fold.to_dict() for fold in self.folds],
            "aggregate_portfolio_metrics": dict(self.aggregate_portfolio_metrics),
            "promotion_eligible_folds": self.promotion_eligible_folds,
            "scope": (
                "agent-generated factor discovery on PIT historical data; fold-local inner "
                "selection, multiplicity correction, deterministic alpha calibration/risk/"
                "portfolio construction and next-open historical execution"
            ),
        }

    def write_json(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(), sort_keys=True, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return path


class MarketFeatureCandidateGenerator(Protocol):
    def generate(
        self,
        *,
        task: AgentTask,
        count: int,
        approved_input_fields: Sequence[str],
        smoke_inputs: Mapping[str, Sequence[int | float | None]],
    ) -> tuple[GeneratedFeatureArtifact, ...]: ...


class LLMMarketFeatureCandidateGenerator:
    """Bounded facade over ``LLMFeatureGenerator`` for market-research candidates."""

    def __init__(self, generator: LLMFeatureGenerator, *, max_candidates: int = 8) -> None:
        if max_candidates < 1:
            raise ValueError("max_candidates must be >= 1")
        self.generator = generator
        self.max_candidates = max_candidates

    def generate(
        self,
        *,
        task: AgentTask,
        count: int,
        approved_input_fields: Sequence[str],
        smoke_inputs: Mapping[str, Sequence[int | float | None]],
    ) -> tuple[GeneratedFeatureArtifact, ...]:
        if not 1 <= count <= self.max_candidates:
            raise ValueError("candidate count exceeds LLM market feature budget")
        artifacts: list[GeneratedFeatureArtifact] = []
        digests: set[str] = set()
        feature_ids: set[str] = set()
        for index in range(count):
            child = AgentTask(
                task_id=f"{task.task_id}:feature:{index + 1:02d}",
                objective=(
                    f"{task.objective}\nGenerate distinct bounded candidate {index + 1} of {count}. "
                    "Prefer an economically interpretable hypothesis and do not imitate prior candidates."
                ),
                created_at=task.created_at,
                metadata={
                    **dict(task.metadata),
                    "candidate_index": str(index + 1),
                    "candidate_count": str(count),
                },
            )
            artifact = self.generator.generate(
                task=child,
                approved_input_fields=approved_input_fields,
                smoke_inputs=smoke_inputs,
            ).artifact
            if artifact.digest in digests or artifact.spec.feature_id in feature_ids:
                raise ValueError("LLM generated a duplicate feature candidate inside one frozen family")
            digests.add(artifact.digest)
            feature_ids.add(artifact.spec.feature_id)
            artifacts.append(artifact)
        return tuple(artifacts)


class _ProgramPlanAdapter:
    """Minimal mutable PlanLike surface for the existing program-budget ledger."""

    def __init__(
        self,
        *,
        program_id: str,
        family_id: str,
        alpha: float,
        variants: tuple[object, ...],
    ) -> None:
        self.program_id = program_id
        self.family_id = family_id
        self.alpha = alpha
        self.variants = variants

    def fingerprint(self, task_id: str) -> str:
        payload = {
            "task_id": task_id,
            "program_id": self.program_id,
            "family_id": self.family_id,
            "alpha": self.alpha,
            "candidate_digests": [str(value) for value in self.variants],
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


def one_sided_mean_pvalue(values: Sequence[float]) -> float:
    array = np.asarray(values, dtype=float)
    if array.size < 2:
        return 1.0
    std = float(np.std(array, ddof=1))
    mean = float(np.mean(array))
    if std <= 1e-15:
        return 0.0 if mean > 0 else 1.0
    statistic = mean / (std / math.sqrt(array.size))
    return float(student_t.sf(statistic, df=array.size - 1))


def holm_adjusted_pvalues(pvalues: Mapping[str, float]) -> Mapping[str, float]:
    """Return monotone Holm-adjusted p-values keyed by immutable candidate digest."""

    if not pvalues:
        raise ValueError("pvalues cannot be empty")
    for value in pvalues.values():
        if not 0.0 <= float(value) <= 1.0:
            raise ValueError("pvalues must be in [0, 1]")
    ordered = sorted(
        ((key, float(value)) for key, value in pvalues.items()),
        key=lambda item: (item[1], item[0]),
    )
    total = len(ordered)
    running = 0.0
    adjusted: dict[str, float] = {}
    for rank, (key, value) in enumerate(ordered):
        candidate = min(1.0, (total - rank) * value)
        running = max(running, candidate)
        adjusted[key] = running
    return MappingProxyType(adjusted)


def _trace_selection_score(traces: Sequence[GeneratedFeatureResearchTrace], metric: str) -> float:
    values = [float(trace.metrics[metric]) for trace in traces]
    if not values or not all(np.isfinite(value) for value in values):
        raise ValueError(f"selection metric {metric!r} is missing or non-finite")
    return float(np.mean(values))


def _portfolio_metrics(result) -> dict[str, float]:
    return {
        "total_return": float(result.total_return),
        "annualized_return": float(result.annualized_return),
        "annualized_volatility": float(result.annualized_volatility),
        "sharpe": float(result.sharpe),
        "max_drawdown": float(result.max_drawdown),
        "gross_traded_weight": float(result.total_turnover),
        "transaction_cost": float(result.total_transaction_cost),
    }


def _period_returns(result, initial_cash: float) -> list[float]:
    nav = np.asarray([initial_cash, *(point.nav for point in result.points)], dtype=float)
    return [float(value) for value in nav[1:] / nav[:-1] - 1.0]


def _aggregate_portfolio(
    returns: Sequence[float], turnover: float, cost: float
) -> dict[str, float]:
    values = np.asarray(returns, dtype=float)
    if values.size == 0:
        raise ValueError("agent market study produced no out-of-sample portfolio returns")
    wealth = np.cumprod(1.0 + values)
    total_return = float(wealth[-1] - 1.0)
    annualized_return = float(wealth[-1] ** (252.0 / len(values)) - 1.0)
    std = float(np.std(values, ddof=1)) if len(values) > 1 else 0.0
    annualized_volatility = std * math.sqrt(252.0)
    sharpe = float(np.mean(values) / std * math.sqrt(252.0)) if std > 0 else 0.0
    full_wealth = np.concatenate(([1.0], wealth))
    running_max = np.maximum.accumulate(full_wealth)
    return {
        "oos_periods": float(len(values)),
        "total_return": total_return,
        "annualized_return": annualized_return,
        "annualized_volatility": annualized_volatility,
        "sharpe": sharpe,
        "max_drawdown": float(np.min(full_wealth / running_max - 1.0)),
        "gross_traded_weight": float(turnover),
        "transaction_cost": float(cost),
    }


class AgentMarketResearchRunner:
    """Connect generated hypotheses to real-market, nested, deterministic portfolios.

    Candidate selection is fold-local: only inner-validation evidence may choose the
    candidate whose outer fold is reported and traded. Outer results of non-selected
    candidates are never exposed by ``AgentMarketResearchResult``. Holm correction is
    applied across the frozen candidate family within every outer fold.
    """

    def __init__(
        self,
        *,
        adapter,
        capabilities: ProviderCapabilities,
        requirement: ResearchDataRequirement,
        program_store: SQLiteResearchProgramStore,
        config: AgentMarketResearchConfig | None = None,
    ) -> None:
        requirement.require(capabilities)
        self.adapter = adapter
        self.capabilities = capabilities
        self.requirement = requirement
        self.program_store = program_store
        self.config = config or AgentMarketResearchConfig()

    def run(
        self,
        *,
        task: AgentTask,
        candidates: Sequence[GeneratedFeatureArtifact],
        universe: tuple[AssetId, ...],
        start: datetime,
        end: datetime,
        program_id: str,
        family_id: str,
    ) -> AgentMarketResearchResult:
        candidates = tuple(candidates)
        if not candidates or len(candidates) > self.config.max_candidates:
            raise ValueError("candidate family is empty or exceeds configured budget")
        if len({artifact.digest for artifact in candidates}) != len(candidates):
            raise ValueError("candidate family contains duplicate feature digests")
        if len({artifact.spec.feature_id for artifact in candidates}) != len(candidates):
            raise ValueError("candidate family contains duplicate feature ids")
        if len(universe) < 2 or len(set(universe)) != len(universe):
            raise ValueError("agent market research requires at least two unique assets")
        if any(asset.asset_type is not AssetType.ETF for asset in universe):
            raise ValueError("FinAgent 1.2 agent market research is ETF-first")
        if len({asset.currency for asset in universe}) != 1:
            raise ValueError("FinAgent 1.2 requires a single base currency")
        if end <= start:
            raise ValueError("end must be later than start")

        plan = _ProgramPlanAdapter(
            program_id=program_id,
            family_id=family_id,
            alpha=self.config.family_alpha,
            variants=tuple(artifact.digest for artifact in candidates),
        )
        self.program_store.reserve_plan(plan, task_id=task.task_id)

        evaluation_config = GeneratedFeatureEvaluationConfig(
            label_name=self.config.label_name,
            split_name="test",
            transaction_cost_bps=self.config.transaction_cost_bps,
            min_cross_section=self.config.min_cross_section,
            min_periods=self.config.min_periods,
        )
        splitter = self.config.market.splitter()
        studies = {
            artifact.digest: GeneratedFeatureNestedWalkForwardStudy(
                adapter=self.adapter,
                splitter=splitter,
                config=evaluation_config,
            ).run(
                artifact,
                universe=universe,
                start=start,
                end=end,
                dataset_id_prefix=f"agent-market-{family_id}-{artifact.spec.feature_id}",
            )
            for artifact in candidates
        }
        calendar = self.adapter.calendar(start, end, universe)
        nested_folds = splitter.split(calendar, labels=(self.config.label_name,))
        if not nested_folds:
            raise ValueError("agent market research produced no nested folds")
        if any(
            len(studies[artifact.digest].folds) != len(nested_folds) for artifact in candidates
        ):
            raise RuntimeError("candidate studies disagree on nested fold count")

        fold_results: list[AgentMarketFoldResult] = []
        portfolio_returns: list[float] = []
        total_turnover = 0.0
        total_cost = 0.0
        accepted_folds = 0
        artifacts_by_digest = {artifact.digest: artifact for artifact in candidates}

        for fold_position, nested_fold in enumerate(nested_folds):
            scores: dict[str, float] = {}
            raw_pvalues: dict[str, float] = {}
            for artifact in candidates:
                fold = studies[artifact.digest].folds[fold_position]
                scores[artifact.digest] = _trace_selection_score(
                    fold.inner_validation,
                    self.config.selection_metric,
                )
                pooled = [
                    value
                    for trace in fold.inner_validation
                    for value in trace.net_returns
                ]
                raw_pvalues[artifact.digest] = one_sided_mean_pvalue(pooled)
            adjusted = holm_adjusted_pvalues(raw_pvalues)
            accepted = [
                digest for digest in scores if adjusted[digest] <= self.config.family_alpha
            ]
            pool = accepted or list(scores)
            selected_digest = min(pool, key=lambda digest: (-scores[digest], digest))
            statistically_accepted = selected_digest in accepted
            if statistically_accepted:
                accepted_folds += 1
            if self.config.require_statistical_acceptance and not statistically_accepted:
                raise PermissionError(
                    "no generated feature survives inner-fold multiplicity control; "
                    "promotion-style portfolio evaluation is blocked"
                )
            selected = artifacts_by_digest[selected_digest]
            selected_signal_fold = studies[selected_digest].folds[fold_position]

            outer = nested_fold.outer_fold
            risk_features = ("log_return_1", "squared_log_return_1")
            required_features = tuple(
                dict.fromkeys((*selected.spec.input_fields, *risk_features))
            )
            dataset = self.adapter.build_dataset(
                DatasetRequest(
                    universe=universe,
                    features=required_features,
                    labels=(self.config.label_name,),
                    splits={"train": outer.train, "test": outer.test},
                    dataset_id=f"agent-market-portfolio-{family_id}-outer-{outer.fold_index:03d}",
                    metadata={
                        "task_id": task.task_id,
                        "program_id": program_id,
                        "family_id": family_id,
                        "selected_feature_digest": selected_digest,
                        "provider": self.capabilities.provider,
                    },
                )
            )
            market = self.config.market
            alpha = GeneratedFeatureAlphaModel(
                selected,
                label_name=self.config.label_name,
                min_observations=max(10, market.ar_min_observations),
            )
            risk = GARCH11RiskModel(
                min_observations=market.garch_min_observations,
                correlation_lookback=market.correlation_lookback,
            )
            optimizer = MeanVarianceOptimizer(
                MeanVarianceConfig(
                    risk_aversion=market.risk_aversion,
                    cash_weight=market.cash_weight,
                    long_only=True,
                    max_abs_weight=market.max_weight,
                    turnover_penalty=market.turnover_penalty,
                )
            )
            gate = StaticRiskGate(
                max_gross_exposure=1.0,
                max_abs_weight=market.max_weight,
                min_cash_weight=market.cash_weight - 1e-9,
            )
            engine = TimedEventDrivenBacktestEngine(
                self.adapter,
                self.adapter,
                config=TimedBacktestConfig(
                    train_split="train",
                    test_split="test",
                    initial_cash=market.initial_cash,
                    lookback=max(market.lookback, selected.spec.lookback),
                    rebalance_every=market.rebalance_every,
                    execution_lag_events=market.execution_lag_events,
                    execution_price_field="open",
                    annualization_factor=252.0,
                ),
                exchange=TimedSimulatedExchange(
                    slippage_bps=market.slippage_bps,
                    commission_bps=market.commission_bps,
                    impact_bps=market.impact_bps,
                    max_participation_rate=market.max_participation_rate,
                ),
            )
            portfolio = engine.run(dataset, alpha, risk, optimizer, gate)
            if any(point.cash < -1e-8 for point in portfolio.points):
                raise RuntimeError("agent-selected next-open portfolio produced negative cash")
            portfolio_returns.extend(_period_returns(portfolio, market.initial_cash))
            total_turnover += portfolio.total_turnover
            total_cost += portfolio.total_transaction_cost
            fold_results.append(
                AgentMarketFoldResult(
                    outer_fold_index=outer.fold_index,
                    selected_feature_id=selected.spec.feature_id,
                    selected_feature_digest=selected_digest,
                    statistically_accepted=statistically_accepted,
                    inner_mean_scores=scores,
                    inner_raw_pvalues=raw_pvalues,
                    inner_adjusted_pvalues=adjusted,
                    signal_outer_metrics=selected_signal_fold.outer_test.metrics,
                    portfolio_outer_metrics=_portfolio_metrics(portfolio),
                    outer_start=outer.test.start.isoformat(),
                    outer_end=outer.test.end.isoformat(),
                )
            )

        digest_payload = {
            "task_id": task.task_id,
            "program_id": program_id,
            "family_id": family_id,
            "provider": self.capabilities.provider,
            "data_version": self.adapter.data_version,
            "universe": [asset.key for asset in universe],
            "candidates": [artifact.digest for artifact in candidates],
            "start": start.isoformat(),
            "end": end.isoformat(),
            "config": {
                "max_candidates": self.config.max_candidates,
                "family_alpha": self.config.family_alpha,
                "selection_metric": self.config.selection_metric,
                "label_name": self.config.label_name,
                "transaction_cost_bps": self.config.transaction_cost_bps,
                "market": asdict(self.config.market),
            },
        }
        encoded = json.dumps(digest_payload, sort_keys=True, separators=(",", ":")).encode()
        return AgentMarketResearchResult(
            study_id=f"agent-market-{hashlib.sha256(encoded).hexdigest()[:16]}",
            task_id=task.task_id,
            program_id=program_id,
            family_id=family_id,
            provider=self.capabilities.provider,
            data_version=self.adapter.data_version,
            universe=tuple(asset.key for asset in universe),
            candidates=tuple(
                AgentMarketCandidate.from_artifact(artifact) for artifact in candidates
            ),
            folds=tuple(fold_results),
            aggregate_portfolio_metrics=_aggregate_portfolio(
                portfolio_returns,
                total_turnover,
                total_cost,
            ),
            promotion_eligible_folds=accepted_folds,
        )


class SQLiteAgentMarketResearchStore:
    """Append-only evidence store for end-to-end agent/market studies."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_market_research (
                    study_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    program_id TEXT NOT NULL,
                    family_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    data_version TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )

    def register(self, result: AgentMarketResearchResult) -> None:
        encoded = json.dumps(
            result.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        row = (
            result.study_id,
            result.task_id,
            result.program_id,
            result.family_id,
            result.provider,
            result.data_version,
            encoded,
        )
        with sqlite3.connect(self.path) as con:
            existing = con.execute(
                "SELECT task_id, program_id, family_id, provider, data_version, payload_json "
                "FROM agent_market_research WHERE study_id=?",
                (result.study_id,),
            ).fetchone()
            if existing is not None:
                if tuple(existing) != row[1:]:
                    raise ValueError(f"agent market research {result.study_id!r} is immutable")
                return
            con.execute("INSERT INTO agent_market_research VALUES (?, ?, ?, ?, ?, ?, ?)", row)

    def get(self, study_id: str) -> Mapping[str, object]:
        with sqlite3.connect(self.path) as con:
            row = con.execute(
                "SELECT payload_json FROM agent_market_research WHERE study_id=?",
                (study_id,),
            ).fetchone()
        if row is None:
            raise KeyError(study_id)
        return MappingProxyType(json.loads(row[0]))
