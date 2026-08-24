from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Mapping, Sequence, TYPE_CHECKING

import numpy as np

from finagent.domain._validation import freeze_mapping, require_aware_datetime, require_non_empty
from finagent.domain.forecasts import AlphaForecast, RiskForecast
from finagent.domain.portfolio import PortfolioState
from finagent.portfolio.benchmarks import PortfolioBenchmarkResult
from finagent.portfolio.stress import RebalanceDecision, StressTestReport

from .domain import (
    AgentAction,
    AgentDecision,
    AgentDecisionStatus,
    AgentRunContext,
    AgentTask,
    PolicyDecision,
    PolicyOutcome,
    ToolCallRequest,
    ToolCallStatus,
)

if TYPE_CHECKING:
    from .tools.base import ToolRegistry, ToolSpec


class HealthLevel(str, Enum):
    OK = "ok"
    WARNING = "warning"
    CRITICAL = "critical"


_LEVEL_ORDER = {
    HealthLevel.OK: 0,
    HealthLevel.WARNING: 1,
    HealthLevel.CRITICAL: 2,
}


@dataclass(frozen=True, slots=True)
class HealthCheck:
    name: str
    level: HealthLevel
    message: str
    observed: float | None = None
    limit: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", require_non_empty(self.name, "health check name"))
        object.__setattr__(self, "message", require_non_empty(self.message, "health check message"))
        if self.observed is not None and not np.isfinite(self.observed):
            raise ValueError("health check observed value must be finite")
        if self.limit is not None and not np.isfinite(self.limit):
            raise ValueError("health check limit must be finite")


@dataclass(frozen=True, slots=True)
class PortfolioBenchmarkSummary:
    name: str
    expected_return: float
    expected_net_return: float
    volatility: float
    turnover: float
    gross_exposure: float
    net_exposure: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", require_non_empty(self.name, "benchmark name"))
        values = (
            self.expected_return,
            self.expected_net_return,
            self.volatility,
            self.turnover,
            self.gross_exposure,
            self.net_exposure,
        )
        if not all(np.isfinite(value) for value in values):
            raise ValueError("benchmark summary values must be finite")


@dataclass(frozen=True, slots=True)
class PortfolioStressSummary:
    name: str
    portfolio_return: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", require_non_empty(self.name, "scenario name"))
        if not np.isfinite(self.portfolio_return):
            raise ValueError("scenario return must be finite")


@dataclass(frozen=True, slots=True)
class WeightDriftSummary:
    asset_key: str
    current_weight: float
    target_weight: float
    delta: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "asset_key", require_non_empty(self.asset_key, "asset_key"))
        if not all(np.isfinite(value) for value in (self.current_weight, self.target_weight, self.delta)):
            raise ValueError("weight drift values must be finite")


@dataclass(frozen=True, slots=True)
class PortfolioHealthSnapshot:
    snapshot_id: str
    asof: datetime
    observed_at: datetime
    data_asof: datetime
    selected_constructor: str
    checks: tuple[HealthCheck, ...]
    benchmarks: tuple[PortfolioBenchmarkSummary, ...]
    stresses: tuple[PortfolioStressSummary, ...]
    weight_drifts: tuple[WeightDriftSummary, ...]
    rebalance_required: bool
    rebalance_turnover: float
    rebalance_max_weight_drift: float
    rebalance_reasons: tuple[str, ...] = ()
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "snapshot_id", require_non_empty(self.snapshot_id, "snapshot_id"))
        object.__setattr__(self, "asof", require_aware_datetime(self.asof, "asof"))
        object.__setattr__(self, "observed_at", require_aware_datetime(self.observed_at, "observed_at"))
        object.__setattr__(self, "data_asof", require_aware_datetime(self.data_asof, "data_asof"))
        object.__setattr__(
            self,
            "selected_constructor",
            require_non_empty(self.selected_constructor, "selected_constructor"),
        )
        if not self.benchmarks:
            raise ValueError("portfolio health snapshot requires benchmark results")
        if self.selected_constructor not in {item.name for item in self.benchmarks}:
            raise ValueError("selected_constructor must identify one benchmark result")
        if not np.isfinite(self.rebalance_turnover) or self.rebalance_turnover < 0:
            raise ValueError("rebalance_turnover must be finite and >= 0")
        if not np.isfinite(self.rebalance_max_weight_drift) or self.rebalance_max_weight_drift < 0:
            raise ValueError("rebalance_max_weight_drift must be finite and >= 0")
        object.__setattr__(self, "metadata", freeze_mapping(self.metadata))
        object.__setattr__(
            self,
            "rebalance_reasons",
            tuple(require_non_empty(reason, "rebalance reason") for reason in self.rebalance_reasons),
        )

    @property
    def overall_level(self) -> HealthLevel:
        if not self.checks:
            return HealthLevel.OK
        return max((check.level for check in self.checks), key=lambda level: _LEVEL_ORDER[level])

    @property
    def selected_benchmark(self) -> PortfolioBenchmarkSummary:
        return next(item for item in self.benchmarks if item.name == self.selected_constructor)

    @property
    def worst_stress(self) -> PortfolioStressSummary | None:
        return min(self.stresses, key=lambda item: item.portfolio_return) if self.stresses else None


@dataclass(frozen=True, slots=True)
class PortfolioHealthThresholds:
    max_data_age: timedelta | None = None
    max_forecast_age: timedelta | None = None
    min_expected_net_return: float | None = None
    max_volatility: float | None = None
    max_turnover: float | None = None
    max_stress_loss: float | None = None

    def __post_init__(self) -> None:
        for name in ("max_data_age", "max_forecast_age"):
            value = getattr(self, name)
            if value is not None and value <= timedelta(0):
                raise ValueError(f"{name} must be positive when configured")
        for name in ("min_expected_net_return", "max_volatility", "max_turnover", "max_stress_loss"):
            value = getattr(self, name)
            if value is not None and not np.isfinite(value):
                raise ValueError(f"{name} must be finite when configured")
        for name in ("max_volatility", "max_turnover", "max_stress_loss"):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise ValueError(f"{name} must be >= 0 when configured")


class PortfolioHealthMonitor:
    """Build a deterministic, immutable health snapshot from Phase 4 outputs."""

    def __init__(self, thresholds: PortfolioHealthThresholds | None = None) -> None:
        self.thresholds = thresholds or PortfolioHealthThresholds()

    def build(
        self,
        *,
        snapshot_id: str,
        observed_at: datetime,
        data_asof: datetime,
        alpha: AlphaForecast,
        risk: RiskForecast,
        state: PortfolioState,
        benchmarks: Sequence[PortfolioBenchmarkResult],
        stress_report: StressTestReport,
        rebalance: RebalanceDecision,
        selected_constructor: str,
        metadata: Mapping[str, str] | None = None,
    ) -> PortfolioHealthSnapshot:
        observed_at = require_aware_datetime(observed_at, "observed_at")
        data_asof = require_aware_datetime(data_asof, "data_asof")
        if data_asof > observed_at or alpha.asof > observed_at or risk.asof > observed_at:
            raise ValueError("health inputs cannot be dated after observed_at")
        benchmark_results = tuple(benchmarks)
        if not benchmark_results:
            raise ValueError("benchmarks cannot be empty")
        selected = next((item for item in benchmark_results if item.name == selected_constructor), None)
        if selected is None:
            raise KeyError(f"selected constructor {selected_constructor!r} is absent from benchmarks")
        if selected.target.asof != state.asof:
            raise ValueError("selected target and portfolio state must share asof")

        checks: list[HealthCheck] = []
        if alpha.asof != risk.asof or alpha.asof != state.asof:
            checks.append(
                HealthCheck(
                    "forecast_alignment",
                    HealthLevel.CRITICAL,
                    "alpha, risk and portfolio state clocks are not aligned",
                )
            )
        else:
            checks.append(
                HealthCheck("forecast_alignment", HealthLevel.OK, "forecast and portfolio clocks are aligned")
            )

        if self.thresholds.max_data_age is not None:
            age = (observed_at - data_asof).total_seconds()
            limit = self.thresholds.max_data_age.total_seconds()
            level = HealthLevel.CRITICAL if age > limit else HealthLevel.OK
            checks.append(HealthCheck("data_freshness", level, "data age checked against policy", age, limit))
        if self.thresholds.max_forecast_age is not None:
            age = (observed_at - min(alpha.asof, risk.asof)).total_seconds()
            limit = self.thresholds.max_forecast_age.total_seconds()
            level = HealthLevel.CRITICAL if age > limit else HealthLevel.OK
            checks.append(HealthCheck("forecast_freshness", level, "forecast age checked against policy", age, limit))

        metrics = selected.metrics
        if self.thresholds.min_expected_net_return is not None:
            observed = metrics.expected_net_return
            limit = self.thresholds.min_expected_net_return
            level = HealthLevel.WARNING if observed < limit else HealthLevel.OK
            checks.append(HealthCheck("expected_net_return", level, "selected portfolio expected net return", observed, limit))
        if self.thresholds.max_volatility is not None:
            observed = metrics.volatility
            limit = self.thresholds.max_volatility
            level = HealthLevel.WARNING if observed > limit else HealthLevel.OK
            checks.append(HealthCheck("portfolio_volatility", level, "selected portfolio forecast volatility", observed, limit))
        if self.thresholds.max_turnover is not None:
            observed = metrics.turnover
            limit = self.thresholds.max_turnover
            level = HealthLevel.WARNING if observed > limit else HealthLevel.OK
            checks.append(HealthCheck("portfolio_turnover", level, "selected portfolio turnover", observed, limit))

        worst = stress_report.worst
        if self.thresholds.max_stress_loss is not None:
            observed_loss = max(-float(worst.portfolio_return), 0.0)
            limit = self.thresholds.max_stress_loss
            level = HealthLevel.CRITICAL if observed_loss > limit else HealthLevel.OK
            checks.append(HealthCheck("stress_loss", level, f"worst scenario: {worst.name}", observed_loss, limit))

        checks.append(
            HealthCheck(
                "rebalance",
                HealthLevel.WARNING if rebalance.rebalance else HealthLevel.OK,
                "deterministic rebalance policy requested action" if rebalance.rebalance else "no rebalance required",
                rebalance.turnover,
                None,
            )
        )

        benchmark_summaries = tuple(
            PortfolioBenchmarkSummary(
                item.name,
                item.metrics.expected_return,
                item.metrics.expected_net_return,
                item.metrics.volatility,
                item.metrics.turnover,
                item.metrics.gross_exposure,
                item.metrics.net_exposure,
            )
            for item in benchmark_results
        )
        stress_summaries = tuple(
            PortfolioStressSummary(item.name, item.portfolio_return) for item in stress_report.results
        )
        assets = tuple(sorted(set(selected.target.weights) | set(state.positions)))
        drifts = sorted(
            (
                WeightDriftSummary(
                    asset.key,
                    state.weight(asset),
                    selected.target.weights.get(asset, 0.0),
                    selected.target.weights.get(asset, 0.0) - state.weight(asset),
                )
                for asset in assets
            ),
            key=lambda item: (-abs(item.delta), item.asset_key),
        )
        snapshot_metadata = {
            "alpha_source": f"{alpha.source.name}:{alpha.source.version}",
            "risk_source": f"{risk.source.name}:{risk.source.version}",
            **dict(metadata or {}),
        }
        return PortfolioHealthSnapshot(
            snapshot_id=snapshot_id,
            asof=state.asof,
            observed_at=observed_at,
            data_asof=data_asof,
            selected_constructor=selected_constructor,
            checks=tuple(checks),
            benchmarks=benchmark_summaries,
            stresses=stress_summaries,
            weight_drifts=tuple(drifts),
            rebalance_required=rebalance.rebalance,
            rebalance_turnover=rebalance.turnover,
            rebalance_max_weight_drift=rebalance.max_weight_drift,
            rebalance_reasons=rebalance.reasons,
            metadata=snapshot_metadata,
        )


class SQLitePortfolioSupervisionStore:
    """Immutable portfolio-health evidence used by Supervisor tools."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS portfolio_supervision_snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    @staticmethod
    def _payload(snapshot: PortfolioHealthSnapshot) -> dict[str, object]:
        return {
            "asof": snapshot.asof.isoformat(),
            "observed_at": snapshot.observed_at.isoformat(),
            "data_asof": snapshot.data_asof.isoformat(),
            "selected_constructor": snapshot.selected_constructor,
            "checks": [
                {
                    "name": item.name,
                    "level": item.level.value,
                    "message": item.message,
                    "observed": item.observed,
                    "limit": item.limit,
                }
                for item in snapshot.checks
            ],
            "benchmarks": [
                {
                    "name": item.name,
                    "expected_return": item.expected_return,
                    "expected_net_return": item.expected_net_return,
                    "volatility": item.volatility,
                    "turnover": item.turnover,
                    "gross_exposure": item.gross_exposure,
                    "net_exposure": item.net_exposure,
                }
                for item in snapshot.benchmarks
            ],
            "stresses": [
                {"name": item.name, "portfolio_return": item.portfolio_return}
                for item in snapshot.stresses
            ],
            "weight_drifts": [
                {
                    "asset_key": item.asset_key,
                    "current_weight": item.current_weight,
                    "target_weight": item.target_weight,
                    "delta": item.delta,
                }
                for item in snapshot.weight_drifts
            ],
            "rebalance_required": snapshot.rebalance_required,
            "rebalance_turnover": snapshot.rebalance_turnover,
            "rebalance_max_weight_drift": snapshot.rebalance_max_weight_drift,
            "rebalance_reasons": list(snapshot.rebalance_reasons),
            "metadata": dict(snapshot.metadata),
        }

    def register(self, snapshot: PortfolioHealthSnapshot) -> None:
        encoded = json.dumps(self._payload(snapshot), sort_keys=True, separators=(",", ":"), allow_nan=False)
        with self._connect() as con:
            row = con.execute(
                "SELECT payload_json FROM portfolio_supervision_snapshots WHERE snapshot_id=?",
                (snapshot.snapshot_id,),
            ).fetchone()
            if row is not None:
                if row[0] != encoded:
                    raise ValueError(f"portfolio supervision snapshot {snapshot.snapshot_id!r} is immutable")
                return
            con.execute(
                "INSERT INTO portfolio_supervision_snapshots VALUES (?, ?)",
                (snapshot.snapshot_id, encoded),
            )

    def get(self, snapshot_id: str) -> PortfolioHealthSnapshot:
        with self._connect() as con:
            row = con.execute(
                "SELECT payload_json FROM portfolio_supervision_snapshots WHERE snapshot_id=?",
                (snapshot_id,),
            ).fetchone()
        if row is None:
            raise KeyError(snapshot_id)
        payload = json.loads(row[0])
        return PortfolioHealthSnapshot(
            snapshot_id=snapshot_id,
            asof=datetime.fromisoformat(payload["asof"]),
            observed_at=datetime.fromisoformat(payload["observed_at"]),
            data_asof=datetime.fromisoformat(payload["data_asof"]),
            selected_constructor=payload["selected_constructor"],
            checks=tuple(
                HealthCheck(
                    item["name"],
                    HealthLevel(item["level"]),
                    item["message"],
                    item["observed"],
                    item["limit"],
                )
                for item in payload["checks"]
            ),
            benchmarks=tuple(PortfolioBenchmarkSummary(**item) for item in payload["benchmarks"]),
            stresses=tuple(PortfolioStressSummary(**item) for item in payload["stresses"]),
            weight_drifts=tuple(WeightDriftSummary(**item) for item in payload["weight_drifts"]),
            rebalance_required=bool(payload["rebalance_required"]),
            rebalance_turnover=float(payload["rebalance_turnover"]),
            rebalance_max_weight_drift=float(payload["rebalance_max_weight_drift"]),
            rebalance_reasons=tuple(payload["rebalance_reasons"]),
            metadata=payload["metadata"],
        )

    def list_snapshot_ids(self) -> tuple[str, ...]:
        with self._connect() as con:
            rows = con.execute(
                "SELECT snapshot_id FROM portfolio_supervision_snapshots ORDER BY snapshot_id"
            ).fetchall()
        return tuple(row[0] for row in rows)


class OperatingMode(str, Enum):
    NORMAL = "normal"
    CAUTIOUS = "cautious"
    DEFENSIVE = "defensive"
    PAUSED = "paused"


@dataclass(frozen=True, slots=True)
class OperatingPolicy:
    policy_id: str
    mode: OperatingMode
    description: str
    constraint_policy_id: str
    rebalance_policy_id: str

    def __post_init__(self) -> None:
        for name in ("policy_id", "description", "constraint_policy_id", "rebalance_policy_id"):
            object.__setattr__(self, name, require_non_empty(getattr(self, name), name))


class OperatingPolicyRegistry:
    def __init__(self, policies: Sequence[OperatingPolicy] = ()) -> None:
        self._policies: dict[str, OperatingPolicy] = {}
        for policy in policies:
            self.register(policy)

    def register(self, policy: OperatingPolicy) -> None:
        if policy.policy_id in self._policies:
            raise ValueError(f"operating policy {policy.policy_id!r} is already registered")
        self._policies[policy.policy_id] = policy

    def get(self, policy_id: str) -> OperatingPolicy:
        try:
            return self._policies[policy_id]
        except KeyError as exc:
            raise KeyError(f"unknown operating policy {policy_id!r}") from exc

    def list(self) -> tuple[OperatingPolicy, ...]:
        return tuple(self._policies[key] for key in sorted(self._policies))

    @classmethod
    def reference(cls) -> "OperatingPolicyRegistry":
        return cls(
            (
                OperatingPolicy("normal", OperatingMode.NORMAL, "standard approved portfolio policy", "constraints-normal", "rebalance-normal"),
                OperatingPolicy("cautious", OperatingMode.CAUTIOUS, "reduced-risk operating policy", "constraints-cautious", "rebalance-cautious"),
                OperatingPolicy("defensive", OperatingMode.DEFENSIVE, "defensive pre-registered portfolio policy", "constraints-defensive", "rebalance-defensive"),
                OperatingPolicy("paused", OperatingMode.PAUSED, "pause new risk pending human review", "constraints-paused", "rebalance-paused"),
            )
        )


@dataclass(frozen=True, slots=True)
class PortfolioSupervisorPolicy:
    """Low-permission Phase 4.5 policy. Supervisor actions never mutate weights or broker state."""

    name: str = "portfolio-supervisor-policy"
    version: str = "1"
    allowed_actions: frozenset[AgentAction] = field(
        default_factory=lambda: frozenset(
            {
                AgentAction.INSPECT_PORTFOLIO_HEALTH,
                AgentAction.INSPECT_PORTFOLIO_BENCHMARKS,
                AgentAction.INSPECT_STRESS_REPORT,
                AgentAction.INSPECT_REBALANCE_DECISION,
                AgentAction.LIST_OPERATING_POLICIES,
                AgentAction.REQUEST_OPERATING_POLICY,
                AgentAction.REQUEST_REBALANCE,
                AgentAction.REQUEST_HUMAN_REVIEW,
            }
        )
    )

    def evaluate(
        self,
        request: ToolCallRequest,
        spec: "ToolSpec",
        context: AgentRunContext,
        *,
        decision_id: str,
        decided_at: datetime,
    ) -> PolicyDecision:
        if context.tool_allowlist and spec.name not in context.tool_allowlist:
            return self._decision(request, context, decision_id, decided_at, PolicyOutcome.DENY, "tool is not present in this run's allowlist")
        if spec.action not in self.allowed_actions:
            return self._decision(request, context, decision_id, decided_at, PolicyOutcome.DENY, "action is outside the Phase 4.5 supervisor surface")
        if spec.action in {AgentAction.REQUEST_OPERATING_POLICY, AgentAction.REQUEST_REBALANCE}:
            return self._decision(request, context, decision_id, decided_at, PolicyOutcome.REQUIRE_HUMAN, "portfolio-state-affecting request requires human approval")
        return self._decision(request, context, decision_id, decided_at, PolicyOutcome.ALLOW, "action is within the Phase 4.5 supervisor surface")

    def _decision(
        self,
        request: ToolCallRequest,
        context: AgentRunContext,
        decision_id: str,
        decided_at: datetime,
        outcome: PolicyOutcome,
        reason: str,
    ) -> PolicyDecision:
        return PolicyDecision(
            decision_id=decision_id,
            run_id=context.run_id,
            call_id=request.call_id,
            tool_name=request.tool_name,
            outcome=outcome,
            reason=reason,
            decided_at=decided_at,
            policy_name=self.name,
            policy_version=self.version,
        )


class ScriptedPortfolioSupervisorAgent:
    """Deterministic reference Supervisor using only governed Phase 4.5 tools."""

    def __init__(self, snapshot_id: str, *, defensive_policy_id: str = "defensive") -> None:
        self.snapshot_id = require_non_empty(snapshot_id, "snapshot_id")
        self.defensive_policy_id = require_non_empty(defensive_policy_id, "defensive_policy_id")

    def run(self, task: AgentTask, tools: "ToolRegistry", context: AgentRunContext) -> AgentDecision:
        call_ids: list[str] = []
        counter = 0

        def invoke(action: AgentAction, arguments: Mapping[str, object]):
            nonlocal counter
            counter += 1
            request = ToolCallRequest(
                call_id=f"{context.run_id}-supervisor-{counter:02d}",
                tool_name=action.value,
                arguments=arguments,
                requested_at=datetime.now(timezone.utc),
            )
            call_ids.append(request.call_id)
            return tools.invoke(request, context)

        read_actions = (
            AgentAction.INSPECT_PORTFOLIO_HEALTH,
            AgentAction.INSPECT_PORTFOLIO_BENCHMARKS,
            AgentAction.INSPECT_STRESS_REPORT,
            AgentAction.INSPECT_REBALANCE_DECISION,
        )
        outputs: dict[AgentAction, Mapping[str, object]] = {}
        for action in read_actions:
            result = invoke(action, {"snapshot_id": self.snapshot_id})
            if result.status is not ToolCallStatus.SUCCEEDED:
                return AgentDecision(
                    context.run_id,
                    AgentDecisionStatus.FAILED,
                    f"supervisor inspection failed at {action.value}: {result.error}",
                    datetime.now(timezone.utc),
                    tuple(call_ids),
                )
            outputs[action] = result.output
        policies = invoke(AgentAction.LIST_OPERATING_POLICIES, {})
        if policies.status is not ToolCallStatus.SUCCEEDED:
            return AgentDecision(context.run_id, AgentDecisionStatus.FAILED, f"operating-policy inspection failed: {policies.error}", datetime.now(timezone.utc), tuple(call_ids))

        health = outputs[AgentAction.INSPECT_PORTFOLIO_HEALTH]
        rebalance = outputs[AgentAction.INSPECT_REBALANCE_DECISION]
        level = HealthLevel(str(health["overall_level"]))
        reason = f"portfolio health is {level.value} for snapshot {self.snapshot_id}"

        if level is HealthLevel.CRITICAL:
            policy_result = invoke(
                AgentAction.REQUEST_OPERATING_POLICY,
                {"snapshot_id": self.snapshot_id, "policy_id": self.defensive_policy_id, "reason": reason},
            )
            if policy_result.status not in {ToolCallStatus.REQUIRES_APPROVAL, ToolCallStatus.SUCCEEDED}:
                return AgentDecision(context.run_id, AgentDecisionStatus.FAILED, f"defensive-policy request failed: {policy_result.error}", datetime.now(timezone.utc), tuple(call_ids))
            review_result = invoke(
                AgentAction.REQUEST_HUMAN_REVIEW,
                {"snapshot_id": self.snapshot_id, "reason": reason},
            )
            if review_result.status is not ToolCallStatus.SUCCEEDED:
                return AgentDecision(context.run_id, AgentDecisionStatus.FAILED, f"human-review request failed: {review_result.error}", datetime.now(timezone.utc), tuple(call_ids))
            return AgentDecision(
                context.run_id,
                AgentDecisionStatus.BLOCKED,
                "critical portfolio health: defensive policy and human review requested; no financial state was mutated",
                datetime.now(timezone.utc),
                tuple(call_ids),
                {"snapshot_id": self.snapshot_id, "recommended_policy": self.defensive_policy_id},
            )

        if level is HealthLevel.WARNING and bool(rebalance["rebalance_required"]):
            result = invoke(
                AgentAction.REQUEST_REBALANCE,
                {"snapshot_id": self.snapshot_id, "reason": reason},
            )
            if result.status not in {ToolCallStatus.REQUIRES_APPROVAL, ToolCallStatus.SUCCEEDED}:
                return AgentDecision(context.run_id, AgentDecisionStatus.FAILED, f"rebalance request failed: {result.error}", datetime.now(timezone.utc), tuple(call_ids))
            return AgentDecision(
                context.run_id,
                AgentDecisionStatus.BLOCKED,
                "warning portfolio health: deterministic rebalance request awaits approval",
                datetime.now(timezone.utc),
                tuple(call_ids),
                {"snapshot_id": self.snapshot_id},
            )

        if level is HealthLevel.WARNING:
            result = invoke(
                AgentAction.REQUEST_HUMAN_REVIEW,
                {"snapshot_id": self.snapshot_id, "reason": reason},
            )
            if result.status is not ToolCallStatus.SUCCEEDED:
                return AgentDecision(context.run_id, AgentDecisionStatus.FAILED, f"human-review request failed: {result.error}", datetime.now(timezone.utc), tuple(call_ids))
            return AgentDecision(
                context.run_id,
                AgentDecisionStatus.BLOCKED,
                "warning portfolio health: human review requested",
                datetime.now(timezone.utc),
                tuple(call_ids),
                {"snapshot_id": self.snapshot_id},
            )

        return AgentDecision(
            context.run_id,
            AgentDecisionStatus.COMPLETED,
            "portfolio health is acceptable; no rebalance or policy-change request was issued",
            datetime.now(timezone.utc),
            tuple(call_ids),
            {"snapshot_id": self.snapshot_id},
        )
