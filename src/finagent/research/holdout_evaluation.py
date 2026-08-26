from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from types import MappingProxyType

from finagent.agents.generated_features import SQLiteGeneratedFeatureStore
from finagent.backtest.market_study import MarketStudyConfig
from finagent.backtest.timed import TimedBacktestConfig, TimedEventDrivenBacktestEngine
from finagent.domain._validation import require_aware_datetime, require_non_empty
from finagent.domain.experiments import ExperimentResult
from finagent.domain.research import DatasetRequest, TimeRange
from finagent.memory import (
    EvidenceVisibility,
    FailureCategory,
    FailureStage,
    MemoryNode,
    MemoryNodeType,
    SQLiteScopedEvidenceWriter,
)
from finagent.models.alpha import GeneratedFeatureAlphaModel
from finagent.models.risk import GARCH11RiskModel
from finagent.portfolio import MeanVarianceConfig, MeanVarianceOptimizer
from finagent.services import StaticRiskGate, TimedSimulatedExchange

from .final_strategy import FinalStrategySpec, SQLiteFinalStrategyStore
from .holdout import (
    HoldoutEligibilitySeal,
    SQLiteHoldoutEligibilityStore,
    SQLiteSealedHoldoutStore,
)
from .programs import ResearchProgramStatus, SQLiteResearchProgramStore
from .registry import SQLiteResearchRegistry


@dataclass(frozen=True, slots=True)
class HoldoutAcceptancePolicy:
    """Pre-declared deterministic criteria for the single final OOS evaluation."""

    policy_id: str
    program_id: str
    holdout_id: str
    min_oos_periods: int
    min_net_sharpe: float
    min_total_return: float
    max_drawdown_limit: float
    created_at: datetime

    def __post_init__(self) -> None:
        for name in ("policy_id", "program_id", "holdout_id"):
            object.__setattr__(self, name, require_non_empty(getattr(self, name), name))
        if isinstance(self.min_oos_periods, bool) or self.min_oos_periods < 2:
            raise ValueError("min_oos_periods must be an integer >= 2")
        for name in ("min_net_sharpe", "min_total_return", "max_drawdown_limit"):
            value = float(getattr(self, name))
            if not math.isfinite(value):
                raise ValueError(f"{name} must be finite")
            object.__setattr__(self, name, value)
        if not 0.0 <= self.max_drawdown_limit < 1.0:
            raise ValueError("max_drawdown_limit must be in [0, 1)")
        object.__setattr__(
            self,
            "created_at",
            require_aware_datetime(self.created_at, "created_at"),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "finagent.holdout-acceptance-policy.v1",
            "policy_id": self.policy_id,
            "program_id": self.program_id,
            "holdout_id": self.holdout_id,
            "min_oos_periods": self.min_oos_periods,
            "min_net_sharpe": self.min_net_sharpe,
            "min_total_return": self.min_total_return,
            "max_drawdown_limit": self.max_drawdown_limit,
            "created_at": self.created_at.isoformat(),
        }

    @property
    def policy_digest(self) -> str:
        encoded = json.dumps(
            self.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
        return hashlib.sha256(encoded).hexdigest()

    def evaluate(self, metrics: Mapping[str, float]) -> tuple[bool, tuple[str, ...]]:
        required = ("oos_periods", "sharpe", "total_return", "max_drawdown")
        missing = [name for name in required if name not in metrics]
        if missing:
            raise KeyError(f"holdout metrics missing acceptance fields: {missing}")
        values = {name: float(metrics[name]) for name in required}
        if not all(math.isfinite(value) for value in values.values()):
            raise ValueError("holdout acceptance metrics must be finite")
        failures: list[str] = []
        if values["oos_periods"] < self.min_oos_periods:
            failures.append(
                f"oos_periods {values['oos_periods']:.0f} < {self.min_oos_periods}"
            )
        if values["sharpe"] < self.min_net_sharpe:
            failures.append(
                f"sharpe {values['sharpe']:.8g} < {self.min_net_sharpe:.8g}"
            )
        if values["total_return"] < self.min_total_return:
            failures.append(
                f"total_return {values['total_return']:.8g} < {self.min_total_return:.8g}"
            )
        if values["max_drawdown"] < -self.max_drawdown_limit:
            failures.append(
                f"max_drawdown {values['max_drawdown']:.8g} < {-self.max_drawdown_limit:.8g}"
            )
        return not failures, tuple(failures)


class SQLiteHoldoutAcceptancePolicyStore:
    """Immutable one-policy-per-program store, preregistered before research begins."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS holdout_acceptance_policies (
                    policy_id TEXT PRIMARY KEY,
                    program_id TEXT NOT NULL UNIQUE,
                    holdout_id TEXT NOT NULL UNIQUE,
                    policy_digest TEXT NOT NULL UNIQUE,
                    payload_json TEXT NOT NULL
                )
                """
            )

    def register_before_research(
        self,
        policy: HoldoutAcceptancePolicy,
        *,
        program_store: SQLiteResearchProgramStore,
        holdout_store: SQLiteSealedHoldoutStore,
    ) -> None:
        program = program_store.get(policy.program_id)
        if program.status is not ResearchProgramStatus.OPEN:
            raise PermissionError("holdout acceptance policy must be registered while program is OPEN")
        if program.sealed_holdout_id != policy.holdout_id:
            raise ValueError("acceptance policy holdout_id does not match ResearchProgram")
        holdout = holdout_store.get(policy.holdout_id)
        if holdout.program_id != policy.program_id:
            raise ValueError("acceptance policy and sealed holdout belong to different programs")
        budget = program_store.budget_snapshot(policy.program_id)
        if budget.family_count or budget.experiment_count or budget.alpha_spent > 1e-15:
            raise PermissionError(
                "holdout acceptance policy must be registered before any research budget is spent"
            )
        encoded = json.dumps(
            policy.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        candidate = (
            policy.program_id,
            policy.holdout_id,
            policy.policy_digest,
            encoded,
        )
        with sqlite3.connect(self.path) as con:
            existing = con.execute(
                "SELECT program_id, holdout_id, policy_digest, payload_json "
                "FROM holdout_acceptance_policies WHERE policy_id=?",
                (policy.policy_id,),
            ).fetchone()
            if existing is not None:
                if tuple(existing) != candidate:
                    raise ValueError("holdout acceptance policy identity is immutable")
                return
            if con.execute(
                "SELECT 1 FROM holdout_acceptance_policies WHERE program_id=? OR holdout_id=?",
                (policy.program_id, policy.holdout_id),
            ).fetchone():
                raise ValueError("program/holdout already has a different acceptance policy")
            con.execute(
                "INSERT INTO holdout_acceptance_policies VALUES (?, ?, ?, ?, ?)",
                (policy.policy_id, *candidate),
            )

    def get_for_program(self, program_id: str) -> HoldoutAcceptancePolicy:
        with sqlite3.connect(self.path) as con:
            row = con.execute(
                "SELECT payload_json FROM holdout_acceptance_policies WHERE program_id=?",
                (program_id,),
            ).fetchone()
        if row is None:
            raise KeyError(program_id)
        payload = json.loads(row[0])
        return HoldoutAcceptancePolicy(
            policy_id=payload["policy_id"],
            program_id=payload["program_id"],
            holdout_id=payload["holdout_id"],
            min_oos_periods=int(payload["min_oos_periods"]),
            min_net_sharpe=float(payload["min_net_sharpe"]),
            min_total_return=float(payload["min_total_return"]),
            max_drawdown_limit=float(payload["max_drawdown_limit"]),
            created_at=datetime.fromisoformat(payload["created_at"]),
        )


class HoldoutEvaluationStatus(str, Enum):
    PASSED = "passed"
    REJECTED = "rejected"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class HoldoutEvaluationReport:
    evaluation_id: str
    program_id: str
    holdout_id: str
    holdout_spec_digest: str
    eligibility_seal_id: str
    final_strategy_id: str
    acceptance_policy_id: str
    acceptance_policy_digest: str
    status: HoldoutEvaluationStatus
    dataset_digest: str
    metrics: Mapping[str, float]
    rejection_reasons: tuple[str, ...]
    evidence_key: str
    accessed_at: datetime
    finished_at: datetime
    error_type: str = ""
    error_message: str = ""

    def __post_init__(self) -> None:
        for name in (
            "evaluation_id",
            "program_id",
            "holdout_id",
            "holdout_spec_digest",
            "eligibility_seal_id",
            "final_strategy_id",
            "acceptance_policy_id",
            "acceptance_policy_digest",
            "evidence_key",
        ):
            object.__setattr__(self, name, require_non_empty(getattr(self, name), name))
        metrics = {str(key): float(value) for key, value in self.metrics.items()}
        if any(not math.isfinite(value) for value in metrics.values()):
            raise ValueError("holdout evaluation metrics must be finite")
        object.__setattr__(self, "metrics", MappingProxyType(metrics))
        object.__setattr__(self, "rejection_reasons", tuple(self.rejection_reasons))
        accessed_at = require_aware_datetime(self.accessed_at, "accessed_at")
        finished_at = require_aware_datetime(self.finished_at, "finished_at")
        if finished_at < accessed_at:
            raise ValueError("finished_at cannot precede accessed_at")
        object.__setattr__(self, "accessed_at", accessed_at)
        object.__setattr__(self, "finished_at", finished_at)
        object.__setattr__(self, "error_type", self.error_type.strip())
        object.__setattr__(self, "error_message", self.error_message.strip())
        if self.status is HoldoutEvaluationStatus.ERROR and not self.error_type:
            raise ValueError("ERROR holdout reports require error_type")
        if self.status is not HoldoutEvaluationStatus.ERROR and self.error_type:
            raise ValueError("non-error holdout reports cannot carry error_type")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "finagent.sealed-holdout-evaluation.v1",
            "evaluation_id": self.evaluation_id,
            "program_id": self.program_id,
            "holdout_id": self.holdout_id,
            "holdout_spec_digest": self.holdout_spec_digest,
            "eligibility_seal_id": self.eligibility_seal_id,
            "final_strategy_id": self.final_strategy_id,
            "acceptance_policy_id": self.acceptance_policy_id,
            "acceptance_policy_digest": self.acceptance_policy_digest,
            "status": self.status.value,
            "dataset_digest": self.dataset_digest,
            "metrics": dict(self.metrics),
            "rejection_reasons": list(self.rejection_reasons),
            "evidence_key": self.evidence_key,
            "accessed_at": self.accessed_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
            "error_type": self.error_type,
            "error_message": self.error_message,
        }


class SQLiteHoldoutEvaluationStore:
    """Terminal one-report-per-program audit store. Never used as Agent memory."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS holdout_evaluations (
                    evaluation_id TEXT PRIMARY KEY,
                    program_id TEXT NOT NULL UNIQUE,
                    payload_json TEXT NOT NULL
                )
                """
            )

    def register(self, report: HoldoutEvaluationReport) -> None:
        encoded = json.dumps(
            report.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        with sqlite3.connect(self.path) as con:
            existing = con.execute(
                "SELECT evaluation_id, payload_json FROM holdout_evaluations WHERE program_id=?",
                (report.program_id,),
            ).fetchone()
            if existing is not None:
                if existing[0] != report.evaluation_id or existing[1] != encoded:
                    raise ValueError("ResearchProgram already has a different holdout evaluation")
                return
            con.execute(
                "INSERT INTO holdout_evaluations VALUES (?, ?, ?)",
                (report.evaluation_id, report.program_id, encoded),
            )

    def get_for_program(self, program_id: str) -> HoldoutEvaluationReport:
        with sqlite3.connect(self.path) as con:
            row = con.execute(
                "SELECT payload_json FROM holdout_evaluations WHERE program_id=?",
                (program_id,),
            ).fetchone()
        if row is None:
            raise KeyError(program_id)
        payload = json.loads(row[0])
        return HoldoutEvaluationReport(
            evaluation_id=payload["evaluation_id"],
            program_id=payload["program_id"],
            holdout_id=payload["holdout_id"],
            holdout_spec_digest=payload["holdout_spec_digest"],
            eligibility_seal_id=payload["eligibility_seal_id"],
            final_strategy_id=payload["final_strategy_id"],
            acceptance_policy_id=payload["acceptance_policy_id"],
            acceptance_policy_digest=payload["acceptance_policy_digest"],
            status=HoldoutEvaluationStatus(payload["status"]),
            dataset_digest=payload["dataset_digest"],
            metrics=payload["metrics"],
            rejection_reasons=tuple(payload["rejection_reasons"]),
            evidence_key=payload["evidence_key"],
            accessed_at=datetime.fromisoformat(payload["accessed_at"]),
            finished_at=datetime.fromisoformat(payload["finished_at"]),
            error_type=payload.get("error_type", ""),
            error_message=payload.get("error_message", ""),
        )


class SealedHoldoutEvaluator:
    """Consume one preregistered holdout exactly once and evaluate the frozen strategy."""

    IMPLEMENTATION = {
        "alpha_model": "GeneratedFeatureAlphaModel",
        "risk_model": "GARCH11RiskModel",
        "portfolio_optimizer": "MeanVarianceOptimizer",
        "risk_gate": "StaticRiskGate",
        "execution_engine": "TimedEventDrivenBacktestEngine",
        "execution_price_field": "open",
        "annualization_factor": 252.0,
    }

    def __init__(
        self,
        *,
        adapter,
        generated_feature_store: SQLiteGeneratedFeatureStore,
        research_registry: SQLiteResearchRegistry,
        program_store: SQLiteResearchProgramStore,
        holdout_store: SQLiteSealedHoldoutStore,
        eligibility_store: SQLiteHoldoutEligibilityStore,
        strategy_store: SQLiteFinalStrategyStore,
        policy_store: SQLiteHoldoutAcceptancePolicyStore,
        evaluation_store: SQLiteHoldoutEvaluationStore,
        scoped_evidence_writer: SQLiteScopedEvidenceWriter,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.adapter = adapter
        self.generated_feature_store = generated_feature_store
        self.research_registry = research_registry
        self.program_store = program_store
        self.holdout_store = holdout_store
        self.eligibility_store = eligibility_store
        self.strategy_store = strategy_store
        self.policy_store = policy_store
        self.evaluation_store = evaluation_store
        self.scoped_evidence_writer = scoped_evidence_writer
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    @staticmethod
    def _evaluation_id(
        *,
        program_id: str,
        holdout_digest: str,
        strategy_id: str,
        policy_digest: str,
        seal_id: str,
    ) -> str:
        payload = "|".join(
            (program_id, holdout_digest, strategy_id, policy_digest, seal_id)
        )
        return f"holdout-eval-{hashlib.sha256(payload.encode()).hexdigest()[:24]}"

    @staticmethod
    def _decode_protocol(strategy: FinalStrategySpec):
        payload = json.loads(strategy.research_protocol_json)
        if payload.get("schema_version") != "finagent.final-strategy-protocol.v1":
            raise ValueError("unsupported final strategy protocol schema")
        implementation = payload.get("implementation")
        if implementation != SealedHoldoutEvaluator.IMPLEMENTATION:
            raise ValueError("final strategy implementation protocol drifted before holdout")
        agent = payload.get("agent_market")
        market_payload = payload.get("market")
        if not isinstance(agent, dict) or not isinstance(market_payload, dict):
            raise ValueError("final strategy protocol is missing agent_market/market configuration")
        market = MarketStudyConfig(**market_payload)
        label_name = str(agent.get("label_name", "")).strip()
        if not label_name:
            raise ValueError("final strategy protocol has no label_name")
        return agent, market, label_name

    def _preflight(
        self,
        *,
        strategy: FinalStrategySpec,
        eligibility: HoldoutEligibilitySeal,
    ):
        try:
            existing = self.evaluation_store.get_for_program(strategy.program_id)
        except KeyError:
            existing = None
        if existing is not None:
            if (
                existing.final_strategy_id != strategy.strategy_id
                or existing.eligibility_seal_id != eligibility.seal_id
            ):
                raise ValueError("existing terminal holdout report belongs to different frozen inputs")
            return existing, None

        program = self.program_store.get(strategy.program_id)
        lifecycle = self.program_store.lifecycle_snapshot(strategy.program_id)
        if program.status is not ResearchProgramStatus.FROZEN:
            raise PermissionError("sealed holdout evaluation requires a FROZEN ResearchProgram")
        if lifecycle.holdout_consumed:
            raise PermissionError(
                "sealed holdout was consumed without a terminal report; automatic retry is forbidden"
            )
        holdout = self.holdout_store.get(program.sealed_holdout_id)
        policy = self.policy_store.get_for_program(strategy.program_id)
        stored_strategy = dict(self.strategy_store.get_payload(strategy.strategy_id))
        if stored_strategy != strategy.to_dict():
            raise ValueError("FinalStrategySpec is not the exact frozen strategy persisted in store")
        stored_seal = dict(self.eligibility_store.get_for_program(strategy.program_id))
        if stored_seal != eligibility.to_dict():
            raise ValueError("HoldoutEligibilitySeal is not the exact persisted eligibility seal")
        if eligibility.final_strategy_id != strategy.strategy_id:
            raise ValueError("eligibility seal final strategy identity mismatch")
        if eligibility.holdout_id != holdout.holdout_id:
            raise ValueError("eligibility seal holdout identity mismatch")
        if eligibility.holdout_spec_digest != holdout.spec_digest:
            raise ValueError("eligibility seal holdout digest mismatch")
        if policy.holdout_id != holdout.holdout_id:
            raise ValueError("acceptance policy holdout identity mismatch")
        if tuple(strategy.universe) != tuple(holdout.universe):
            raise ValueError("frozen strategy universe differs from sealed holdout universe")
        if self.adapter.data_version != holdout.data_version:
            raise ValueError("adapter data_version does not match preregistered holdout snapshot")

        experiment = self.research_registry.get_experiment(strategy.selected_experiment_id)
        if str(experiment.metadata.get("generated_feature_digest", "")) != strategy.selected_feature_digest:
            raise ValueError("formal ExperimentSpec feature identity drifted before holdout")
        if experiment.dataset.digest != strategy.primary_dataset.digest:
            raise ValueError("formal ExperimentSpec primary dataset identity drifted")
        feature = self.generated_feature_store.get(strategy.selected_feature_digest)
        if feature.digest != strategy.selected_feature_digest:
            raise ValueError("generated feature store returned a different artifact digest")
        _agent, market, label_name = self._decode_protocol(strategy)

        memory_store = self.scoped_evidence_writer.memory_store
        experiment_key = f"experiment:{strategy.selected_experiment_id}"
        if memory_store.node_exists(experiment_key):
            node = memory_store.get_node(experiment_key)
            if node.metadata.get("fingerprint") != experiment.fingerprint:
                raise ValueError("memory ExperimentSpec fingerprint disagrees with formal registry")
        else:
            memory_store.register_node(
                MemoryNode(
                    MemoryNodeType.EXPERIMENT,
                    strategy.selected_experiment_id,
                    strategy.selected_experiment_id,
                    strategy.created_at,
                    {
                        "fingerprint": experiment.fingerprint,
                        "hypothesis": experiment.hypothesis,
                        "dataset_digest": experiment.dataset.digest,
                        "code_digest": experiment.code.digest,
                        "universe": json.dumps(
                            sorted(asset.key for asset in experiment.universe),
                            separators=(",", ":"),
                        ),
                        "parameters": json.dumps(
                            dict(experiment.parameters),
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                        "seed": str(experiment.seed),
                    },
                )
            )
        return None, (holdout, policy, feature, market, label_name)

    def _build_dataset(self, strategy, holdout, feature, label_name):
        required_features = tuple(
            dict.fromkeys((*feature.spec.input_fields, "log_return_1", "squared_log_return_1"))
        )
        dataset = self.adapter.build_dataset(
            DatasetRequest(
                universe=strategy.universe,
                features=required_features,
                labels=(label_name,),
                splits={
                    "train": TimeRange(holdout.training_start, holdout.training_end),
                    "test": TimeRange(holdout.holdout_start, holdout.holdout_end),
                },
                dataset_id=(
                    f"sealed-holdout-{strategy.program_id}-{holdout.holdout_id}-"
                    f"{strategy.strategy_id}"
                ),
                metadata={
                    "program_id": strategy.program_id,
                    "holdout_id": holdout.holdout_id,
                    "final_strategy_id": strategy.strategy_id,
                    "scope": "sealed_holdout",
                },
            )
        )
        if dataset.artifact.version != holdout.data_version:
            raise ValueError("materialized holdout dataset version differs from preregistered snapshot")
        return dataset

    @staticmethod
    def _run_portfolio(adapter, dataset, feature, market, label_name):
        alpha = GeneratedFeatureAlphaModel(
            feature,
            label_name=label_name,
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
            adapter,
            adapter,
            config=TimedBacktestConfig(
                train_split="train",
                test_split="test",
                initial_cash=market.initial_cash,
                lookback=max(market.lookback, feature.spec.lookback),
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
        result = engine.run(dataset, alpha, risk, optimizer, gate)
        if any(point.cash < -1e-8 for point in result.points):
            raise RuntimeError("sealed holdout next-open portfolio produced negative cash")
        return result

    @staticmethod
    def _metrics(portfolio) -> dict[str, float]:
        return {
            "oos_periods": float(len(portfolio.points)),
            "total_return": float(portfolio.total_return),
            "annualized_return": float(portfolio.annualized_return),
            "annualized_volatility": float(portfolio.annualized_volatility),
            "sharpe": float(portfolio.sharpe),
            "max_drawdown": float(portfolio.max_drawdown),
            "gross_traded_weight": float(portfolio.total_turnover),
            "transaction_cost": float(portfolio.total_transaction_cost),
        }

    def run(
        self,
        *,
        strategy: FinalStrategySpec,
        eligibility: HoldoutEligibilitySeal,
        actor: str,
    ) -> HoldoutEvaluationReport:
        actor = require_non_empty(actor, "actor")
        existing, prepared = self._preflight(strategy=strategy, eligibility=eligibility)
        if existing is not None:
            return existing
        assert prepared is not None
        holdout, policy, feature, market, label_name = prepared
        accessed_at = self.clock()
        self.program_store.consume_sealed_holdout(
            strategy.program_id,
            actor=actor,
            accessed_at=accessed_at,
        )
        evaluation_id = self._evaluation_id(
            program_id=strategy.program_id,
            holdout_digest=holdout.spec_digest,
            strategy_id=strategy.strategy_id,
            policy_digest=policy.policy_digest,
            seal_id=eligibility.seal_id,
        )
        try:
            dataset = self._build_dataset(strategy, holdout, feature, label_name)
            portfolio = self._run_portfolio(
                self.adapter,
                dataset,
                feature,
                market,
                label_name,
            )
            metrics = self._metrics(portfolio)
            passed, reasons = policy.evaluate(metrics)
            status = (
                HoldoutEvaluationStatus.PASSED
                if passed
                else HoldoutEvaluationStatus.REJECTED
            )
            result = ExperimentResult(
                run_id=evaluation_id,
                metrics=metrics,
                passed=passed,
                notes=(
                    f"sealed holdout={holdout.holdout_id}; strategy={strategy.strategy_id}; "
                    f"eligibility={eligibility.seal_id}; policy={policy.policy_id}; "
                    f"dataset={dataset.artifact.digest}; reasons={'; '.join(reasons)}"
                ),
            )
            written = self.scoped_evidence_writer.register_result(
                strategy.selected_experiment_id,
                result,
                self.clock(),
                visibility=EvidenceVisibility.SEALED_HOLDOUT,
                program_id=strategy.program_id,
            )
            report = HoldoutEvaluationReport(
                evaluation_id=evaluation_id,
                program_id=strategy.program_id,
                holdout_id=holdout.holdout_id,
                holdout_spec_digest=holdout.spec_digest,
                eligibility_seal_id=eligibility.seal_id,
                final_strategy_id=strategy.strategy_id,
                acceptance_policy_id=policy.policy_id,
                acceptance_policy_digest=policy.policy_digest,
                status=status,
                dataset_digest=dataset.artifact.digest,
                metrics=metrics,
                rejection_reasons=reasons,
                evidence_key=written.node.key,
                accessed_at=accessed_at,
                finished_at=self.clock(),
            )
            self.evaluation_store.register(report)
            self.program_store.close_program(
                strategy.program_id,
                actor=actor,
                reason=f"sealed holdout evaluation {evaluation_id} reached {status.value}",
                occurred_at=report.finished_at,
            )
            return report
        except Exception as exc:
            failure_id = f"holdout-failure-{hashlib.sha256(evaluation_id.encode()).hexdigest()[:24]}"
            failure, written = self.scoped_evidence_writer.record_failure(
                failure_id=failure_id,
                category=FailureCategory.OPERATIONAL,
                stage=FailureStage.VALIDATION,
                summary=(
                    f"sealed holdout evaluation failed after access: {type(exc).__name__}: {exc}"
                ),
                observed_at=self.clock(),
                visibility=EvidenceVisibility.SEALED_HOLDOUT,
                program_id=strategy.program_id,
                experiment_id=strategy.selected_experiment_id,
                related_node_keys=(f"experiment:{strategy.selected_experiment_id}",),
                metadata={
                    "evaluation_id": evaluation_id,
                    "holdout_id": holdout.holdout_id,
                    "final_strategy_id": strategy.strategy_id,
                    "acceptance_policy_id": policy.policy_id,
                    "exception_type": type(exc).__name__,
                },
            )
            finished_at = self.clock()
            report = HoldoutEvaluationReport(
                evaluation_id=evaluation_id,
                program_id=strategy.program_id,
                holdout_id=holdout.holdout_id,
                holdout_spec_digest=holdout.spec_digest,
                eligibility_seal_id=eligibility.seal_id,
                final_strategy_id=strategy.strategy_id,
                acceptance_policy_id=policy.policy_id,
                acceptance_policy_digest=policy.policy_digest,
                status=HoldoutEvaluationStatus.ERROR,
                dataset_digest="unavailable-after-terminal-error",
                metrics={},
                rejection_reasons=(failure.summary,),
                evidence_key=written.node.key,
                accessed_at=accessed_at,
                finished_at=finished_at,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
            self.evaluation_store.register(report)
            self.program_store.close_program(
                strategy.program_id,
                actor=actor,
                reason=f"sealed holdout evaluation {evaluation_id} terminated with error",
                occurred_at=finished_at,
            )
            return report
