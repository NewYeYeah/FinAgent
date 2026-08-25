from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from finagent.domain._validation import require_aware_datetime, require_non_empty

from .store import SQLitePaperBrokerStore


def _dumps(payload: object) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _finite(value: float, name: str) -> float:
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    return value


@dataclass(frozen=True, slots=True)
class ApprovalControl:
    """Durable validity envelope for one immutable HumanApproval."""

    approval_id: str
    created_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "approval_id", require_non_empty(self.approval_id, "approval_id"))
        created = require_aware_datetime(self.created_at, "created_at")
        expires = require_aware_datetime(self.expires_at, "expires_at")
        if expires <= created:
            raise ValueError("expires_at must be later than created_at")
        object.__setattr__(self, "created_at", created)
        object.__setattr__(self, "expires_at", expires)


@dataclass(frozen=True, slots=True)
class ApprovalRevocation:
    approval_id: str
    revoked_at: datetime
    revoked_by: str
    reason: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "approval_id", require_non_empty(self.approval_id, "approval_id"))
        object.__setattr__(self, "revoked_at", require_aware_datetime(self.revoked_at, "revoked_at"))
        object.__setattr__(self, "revoked_by", require_non_empty(self.revoked_by, "revoked_by"))
        object.__setattr__(self, "reason", require_non_empty(self.reason, "reason"))


@dataclass(frozen=True, slots=True)
class OperationalSession:
    session_id: str
    started_at: datetime
    ended_at: datetime
    start_nav: float
    end_nav: float
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "session_id", require_non_empty(self.session_id, "session_id"))
        start = require_aware_datetime(self.started_at, "started_at")
        end = require_aware_datetime(self.ended_at, "ended_at")
        if end <= start:
            raise ValueError("ended_at must be later than started_at")
        object.__setattr__(self, "started_at", start)
        object.__setattr__(self, "ended_at", end)
        object.__setattr__(self, "start_nav", _finite(self.start_nav, "start_nav"))
        object.__setattr__(self, "end_nav", _finite(self.end_nav, "end_nav"))
        object.__setattr__(
            self,
            "metadata",
            MappingProxyType({str(key): str(value) for key, value in self.metadata.items()}),
        )

    @property
    def return_fraction(self) -> float:
        if abs(self.start_nav) <= 1e-15:
            return 0.0
        return (self.end_nav - self.start_nav) / self.start_nav


class OperationalDrillType(str, Enum):
    RESTART_RECOVERY = "restart_recovery"
    KILL_SWITCH = "kill_switch"
    RECONCILIATION = "reconciliation"


@dataclass(frozen=True, slots=True)
class OperationalDrillResult:
    drill_id: str
    drill_type: OperationalDrillType
    occurred_at: datetime
    passed: bool
    actor: str
    notes: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "drill_id", require_non_empty(self.drill_id, "drill_id"))
        object.__setattr__(self, "occurred_at", require_aware_datetime(self.occurred_at, "occurred_at"))
        object.__setattr__(self, "actor", require_non_empty(self.actor, "actor"))
        object.__setattr__(self, "notes", self.notes.strip())


class OperationalIncidentCategory(str, Enum):
    IDEMPOTENCY = "idempotency"
    RECONCILIATION = "reconciliation"
    RESTART_RECOVERY = "restart_recovery"
    KILL_SWITCH = "kill_switch"
    EXECUTION = "execution"
    APPROVAL = "approval"
    DATA = "data"
    OTHER = "other"


class OperationalIncidentSeverity(str, Enum):
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass(frozen=True, slots=True)
class OperationalIncident:
    incident_id: str
    category: OperationalIncidentCategory
    severity: OperationalIncidentSeverity
    occurred_at: datetime
    summary: str
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "incident_id", require_non_empty(self.incident_id, "incident_id"))
        object.__setattr__(self, "occurred_at", require_aware_datetime(self.occurred_at, "occurred_at"))
        object.__setattr__(self, "summary", require_non_empty(self.summary, "summary"))
        object.__setattr__(
            self,
            "metadata",
            MappingProxyType({str(key): str(value) for key, value in self.metadata.items()}),
        )


@dataclass(frozen=True, slots=True)
class OperationalMetricSnapshot:
    period_start: datetime
    period_end: datetime
    session_count: int
    order_count: int
    rejected_order_count: int
    fill_count: int
    blocked_cycle_count: int
    reconciliation_count: int
    critical_reconciliation_count: int
    kill_switch_trip_count: int
    operational_application_count: int
    drill_count: int
    failed_drill_count: int
    restart_recovery_drill_count: int
    restart_recovery_pass_count: int
    kill_switch_drill_count: int
    kill_switch_drill_pass_count: int
    incident_count: int
    critical_incident_count: int
    idempotency_failure_count: int

    def __post_init__(self) -> None:
        start = require_aware_datetime(self.period_start, "period_start")
        end = require_aware_datetime(self.period_end, "period_end")
        if end <= start:
            raise ValueError("period_end must be later than period_start")
        object.__setattr__(self, "period_start", start)
        object.__setattr__(self, "period_end", end)
        for name in (
            "session_count",
            "order_count",
            "rejected_order_count",
            "fill_count",
            "blocked_cycle_count",
            "reconciliation_count",
            "critical_reconciliation_count",
            "kill_switch_trip_count",
            "operational_application_count",
            "drill_count",
            "failed_drill_count",
            "restart_recovery_drill_count",
            "restart_recovery_pass_count",
            "kill_switch_drill_count",
            "kill_switch_drill_pass_count",
            "incident_count",
            "critical_incident_count",
            "idempotency_failure_count",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be an integer >= 0")

    @property
    def rejected_order_rate(self) -> float:
        return self.rejected_order_count / self.order_count if self.order_count else 0.0

    @property
    def critical_reconciliation_rate(self) -> float:
        if not self.reconciliation_count:
            return 0.0
        return self.critical_reconciliation_count / self.reconciliation_count

    @property
    def digest(self) -> str:
        payload = {
            name: (
                getattr(self, name).isoformat()
                if isinstance(getattr(self, name), datetime)
                else getattr(self, name)
            )
            for name in self.__dataclass_fields__
        }
        return hashlib.sha256(_dumps(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class AcceptanceCheck:
    name: str
    passed: bool
    actual: str
    requirement: str
    detail: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", require_non_empty(self.name, "name"))
        object.__setattr__(self, "actual", require_non_empty(self.actual, "actual"))
        object.__setattr__(self, "requirement", require_non_empty(self.requirement, "requirement"))
        object.__setattr__(self, "detail", self.detail.strip())


@dataclass(frozen=True, slots=True)
class PaperAcceptanceReport:
    report_id: str
    policy_id: str
    policy_version: str
    evaluated_at: datetime
    metrics: OperationalMetricSnapshot
    checks: tuple[AcceptanceCheck, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "report_id", require_non_empty(self.report_id, "report_id"))
        object.__setattr__(self, "policy_id", require_non_empty(self.policy_id, "policy_id"))
        object.__setattr__(self, "policy_version", require_non_empty(self.policy_version, "policy_version"))
        object.__setattr__(self, "evaluated_at", require_aware_datetime(self.evaluated_at, "evaluated_at"))
        if not self.checks:
            raise ValueError("acceptance report requires at least one check")

    @property
    def accepted(self) -> bool:
        return all(check.passed for check in self.checks)


class SQLiteOperationalEvidenceStore:
    """Durable Phase-6A evidence that complements, but does not replace, broker state."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as con:
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS approval_controls (
                    approval_id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS approval_revocations (
                    approval_id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS operational_sessions (
                    session_id TEXT PRIMARY KEY,
                    started_at TEXT NOT NULL,
                    ended_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS operational_drills (
                    drill_id TEXT PRIMARY KEY,
                    drill_type TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    passed INTEGER NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS operational_incidents (
                    incident_id TEXT PRIMARY KEY,
                    category TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS paper_acceptance_reports (
                    report_id TEXT PRIMARY KEY,
                    evaluated_at TEXT NOT NULL,
                    accepted INTEGER NOT NULL,
                    payload_json TEXT NOT NULL
                );
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    @staticmethod
    def _insert_immutable(con: sqlite3.Connection, table: str, key_name: str, key: str, payload: str, extra: tuple[object, ...], columns: str) -> None:
        row = con.execute(
            f"SELECT payload_json FROM {table} WHERE {key_name}=?",
            (key,),
        ).fetchone()
        if row is not None:
            if row[0] != payload:
                raise ValueError(f"{table} record {key!r} is immutable")
            return
        placeholders = ",".join("?" for _ in range(2 + len(extra)))
        con.execute(
            f"INSERT INTO {table}({key_name},{columns},payload_json) VALUES({placeholders})",
            (key, *extra, payload),
        )

    def register_approval_control(self, item: ApprovalControl) -> None:
        payload = _dumps({
            "approval_id": item.approval_id,
            "created_at": item.created_at.isoformat(),
            "expires_at": item.expires_at.isoformat(),
        })
        with self._connect() as con:
            row = con.execute(
                "SELECT payload_json FROM approval_controls WHERE approval_id=?",
                (item.approval_id,),
            ).fetchone()
            if row is not None:
                if row[0] != payload:
                    raise ValueError(f"approval control {item.approval_id!r} is immutable")
                return
            con.execute(
                "INSERT INTO approval_controls(approval_id,payload_json) VALUES(?,?)",
                (item.approval_id, payload),
            )

    def get_approval_control(self, approval_id: str) -> ApprovalControl | None:
        with self._connect() as con:
            row = con.execute(
                "SELECT payload_json FROM approval_controls WHERE approval_id=?",
                (approval_id,),
            ).fetchone()
        if row is None:
            return None
        payload = json.loads(row[0])
        return ApprovalControl(
            payload["approval_id"],
            datetime.fromisoformat(payload["created_at"]),
            datetime.fromisoformat(payload["expires_at"]),
        )

    def revoke_approval(self, item: ApprovalRevocation) -> None:
        payload = _dumps({
            "approval_id": item.approval_id,
            "revoked_at": item.revoked_at.isoformat(),
            "revoked_by": item.revoked_by,
            "reason": item.reason,
        })
        with self._connect() as con:
            row = con.execute(
                "SELECT payload_json FROM approval_revocations WHERE approval_id=?",
                (item.approval_id,),
            ).fetchone()
            if row is not None:
                if row[0] != payload:
                    raise ValueError(f"approval revocation {item.approval_id!r} is immutable")
                return
            con.execute(
                "INSERT INTO approval_revocations(approval_id,payload_json) VALUES(?,?)",
                (item.approval_id, payload),
            )

    def get_approval_revocation(self, approval_id: str) -> ApprovalRevocation | None:
        with self._connect() as con:
            row = con.execute(
                "SELECT payload_json FROM approval_revocations WHERE approval_id=?",
                (approval_id,),
            ).fetchone()
        if row is None:
            return None
        payload = json.loads(row[0])
        return ApprovalRevocation(
            payload["approval_id"],
            datetime.fromisoformat(payload["revoked_at"]),
            payload["revoked_by"],
            payload["reason"],
        )

    def register_session(self, item: OperationalSession) -> None:
        payload = _dumps({
            "session_id": item.session_id,
            "started_at": item.started_at.isoformat(),
            "ended_at": item.ended_at.isoformat(),
            "start_nav": item.start_nav,
            "end_nav": item.end_nav,
            "metadata": dict(item.metadata),
        })
        with self._connect() as con:
            row = con.execute(
                "SELECT payload_json FROM operational_sessions WHERE session_id=?",
                (item.session_id,),
            ).fetchone()
            if row is not None:
                if row[0] != payload:
                    raise ValueError(f"operational session {item.session_id!r} is immutable")
                return
            con.execute(
                "INSERT INTO operational_sessions(session_id,started_at,ended_at,payload_json) VALUES(?,?,?,?)",
                (item.session_id, item.started_at.isoformat(), item.ended_at.isoformat(), payload),
            )

    def list_sessions(self) -> tuple[OperationalSession, ...]:
        with self._connect() as con:
            rows = con.execute(
                "SELECT payload_json FROM operational_sessions ORDER BY started_at,session_id"
            ).fetchall()
        items = []
        for row in rows:
            payload = json.loads(row[0])
            items.append(OperationalSession(
                payload["session_id"],
                datetime.fromisoformat(payload["started_at"]),
                datetime.fromisoformat(payload["ended_at"]),
                float(payload["start_nav"]),
                float(payload["end_nav"]),
                payload.get("metadata", {}),
            ))
        return tuple(items)

    def register_drill(self, item: OperationalDrillResult) -> None:
        payload = _dumps({
            "drill_id": item.drill_id,
            "drill_type": item.drill_type.value,
            "occurred_at": item.occurred_at.isoformat(),
            "passed": item.passed,
            "actor": item.actor,
            "notes": item.notes,
        })
        with self._connect() as con:
            row = con.execute(
                "SELECT payload_json FROM operational_drills WHERE drill_id=?",
                (item.drill_id,),
            ).fetchone()
            if row is not None:
                if row[0] != payload:
                    raise ValueError(f"operational drill {item.drill_id!r} is immutable")
                return
            con.execute(
                "INSERT INTO operational_drills(drill_id,drill_type,occurred_at,passed,payload_json) VALUES(?,?,?,?,?)",
                (item.drill_id, item.drill_type.value, item.occurred_at.isoformat(), int(item.passed), payload),
            )

    def list_drills(self) -> tuple[OperationalDrillResult, ...]:
        with self._connect() as con:
            rows = con.execute(
                "SELECT payload_json FROM operational_drills ORDER BY occurred_at,drill_id"
            ).fetchall()
        items = []
        for row in rows:
            payload = json.loads(row[0])
            items.append(OperationalDrillResult(
                payload["drill_id"],
                OperationalDrillType(payload["drill_type"]),
                datetime.fromisoformat(payload["occurred_at"]),
                bool(payload["passed"]),
                payload["actor"],
                payload.get("notes", ""),
            ))
        return tuple(items)

    def register_incident(self, item: OperationalIncident) -> None:
        payload = _dumps({
            "incident_id": item.incident_id,
            "category": item.category.value,
            "severity": item.severity.value,
            "occurred_at": item.occurred_at.isoformat(),
            "summary": item.summary,
            "metadata": dict(item.metadata),
        })
        with self._connect() as con:
            row = con.execute(
                "SELECT payload_json FROM operational_incidents WHERE incident_id=?",
                (item.incident_id,),
            ).fetchone()
            if row is not None:
                if row[0] != payload:
                    raise ValueError(f"operational incident {item.incident_id!r} is immutable")
                return
            con.execute(
                "INSERT INTO operational_incidents(incident_id,category,severity,occurred_at,payload_json) VALUES(?,?,?,?,?)",
                (item.incident_id, item.category.value, item.severity.value, item.occurred_at.isoformat(), payload),
            )

    def list_incidents(self) -> tuple[OperationalIncident, ...]:
        with self._connect() as con:
            rows = con.execute(
                "SELECT payload_json FROM operational_incidents ORDER BY occurred_at,incident_id"
            ).fetchall()
        items = []
        for row in rows:
            payload = json.loads(row[0])
            items.append(OperationalIncident(
                payload["incident_id"],
                OperationalIncidentCategory(payload["category"]),
                OperationalIncidentSeverity(payload["severity"]),
                datetime.fromisoformat(payload["occurred_at"]),
                payload["summary"],
                payload.get("metadata", {}),
            ))
        return tuple(items)

    def register_acceptance_report(self, report: PaperAcceptanceReport) -> None:
        payload = _dumps({
            "report_id": report.report_id,
            "policy_id": report.policy_id,
            "policy_version": report.policy_version,
            "evaluated_at": report.evaluated_at.isoformat(),
            "accepted": report.accepted,
            "metric_digest": report.metrics.digest,
            "checks": [
                {
                    "name": check.name,
                    "passed": check.passed,
                    "actual": check.actual,
                    "requirement": check.requirement,
                    "detail": check.detail,
                }
                for check in report.checks
            ],
        })
        with self._connect() as con:
            row = con.execute(
                "SELECT payload_json FROM paper_acceptance_reports WHERE report_id=?",
                (report.report_id,),
            ).fetchone()
            if row is not None:
                if row[0] != payload:
                    raise ValueError(f"acceptance report {report.report_id!r} is immutable")
                return
            con.execute(
                "INSERT INTO paper_acceptance_reports(report_id,evaluated_at,accepted,payload_json) VALUES(?,?,?,?)",
                (report.report_id, report.evaluated_at.isoformat(), int(report.accepted), payload),
            )


class OperationalJournal:
    """Aggregate durable broker events plus explicit sessions, drills and incidents."""

    def __init__(
        self,
        *,
        broker_store: SQLitePaperBrokerStore,
        evidence_store: SQLiteOperationalEvidenceStore,
    ) -> None:
        self.broker_store = broker_store
        self.evidence_store = evidence_store

    def snapshot(self, *, period_start: datetime, period_end: datetime) -> OperationalMetricSnapshot:
        start = require_aware_datetime(period_start, "period_start")
        end = require_aware_datetime(period_end, "period_end")
        if end <= start:
            raise ValueError("period_end must be later than period_start")

        events = tuple(
            event
            for event in self.broker_store.list_events()
            if start <= datetime.fromisoformat(str(event["occurred_at"])) <= end
        )
        sessions = tuple(
            item
            for item in self.evidence_store.list_sessions()
            if item.ended_at >= start and item.started_at <= end
        )
        drills = tuple(
            item
            for item in self.evidence_store.list_drills()
            if start <= item.occurred_at <= end
        )
        incidents = tuple(
            item
            for item in self.evidence_store.list_incidents()
            if start <= item.occurred_at <= end
        )

        order_events = tuple(event for event in events if event["event_type"] == "order_registered")
        reconciliations = tuple(event for event in events if event["event_type"] == "reconciliation")
        restart_drills = tuple(item for item in drills if item.drill_type is OperationalDrillType.RESTART_RECOVERY)
        kill_drills = tuple(item for item in drills if item.drill_type is OperationalDrillType.KILL_SWITCH)

        return OperationalMetricSnapshot(
            period_start=start,
            period_end=end,
            session_count=len(sessions),
            order_count=len(order_events),
            rejected_order_count=sum(
                str(event["payload"].get("status", "")) == "rejected" for event in order_events
            ),
            fill_count=sum(event["event_type"] == "fill" for event in events),
            blocked_cycle_count=sum(event["event_type"] == "paper_cycle_blocked" for event in events),
            reconciliation_count=len(reconciliations),
            critical_reconciliation_count=sum(
                int(event["payload"].get("critical_count", 0)) for event in reconciliations
            ),
            kill_switch_trip_count=sum(
                event["event_type"] == "kill_switch"
                and str(event["payload"].get("status", "")) == "halted"
                for event in events
            ),
            operational_application_count=sum(
                event["event_type"] == "operational_application" for event in events
            ),
            drill_count=len(drills),
            failed_drill_count=sum(not item.passed for item in drills),
            restart_recovery_drill_count=len(restart_drills),
            restart_recovery_pass_count=sum(item.passed for item in restart_drills),
            kill_switch_drill_count=len(kill_drills),
            kill_switch_drill_pass_count=sum(item.passed for item in kill_drills),
            incident_count=len(incidents),
            critical_incident_count=sum(
                item.severity is OperationalIncidentSeverity.CRITICAL for item in incidents
            ),
            idempotency_failure_count=sum(
                item.category is OperationalIncidentCategory.IDEMPOTENCY for item in incidents
            ),
        )


@dataclass(frozen=True, slots=True)
class PaperAcceptancePolicy:
    policy_id: str = "paper-acceptance-v1"
    version: str = "1"
    min_sessions: int = 20
    min_reconciliations: int = 20
    max_rejected_order_rate: float = 0.02
    max_critical_reconciliation_rate: float = 0.0
    max_kill_switch_trips: int = 0
    min_restart_recovery_drills: int = 2
    min_kill_switch_drills: int = 2
    max_critical_incidents: int = 0
    max_idempotency_failures: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "policy_id", require_non_empty(self.policy_id, "policy_id"))
        object.__setattr__(self, "version", require_non_empty(self.version, "version"))
        for name in (
            "min_sessions",
            "min_reconciliations",
            "max_kill_switch_trips",
            "min_restart_recovery_drills",
            "min_kill_switch_drills",
            "max_critical_incidents",
            "max_idempotency_failures",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be an integer >= 0")
        for name in ("max_rejected_order_rate", "max_critical_reconciliation_rate"):
            value = float(getattr(self, name))
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be in [0, 1]")


class PaperAcceptanceEvaluator:
    """Pre-registered evidence gate for sustained paper/shadow reliability."""

    def __init__(
        self,
        *,
        journal: OperationalJournal,
        evidence_store: SQLiteOperationalEvidenceStore,
        policy: PaperAcceptancePolicy | None = None,
    ) -> None:
        self.journal = journal
        self.evidence_store = evidence_store
        self.policy = policy or PaperAcceptancePolicy()

    def evaluate(
        self,
        *,
        period_start: datetime,
        period_end: datetime,
        evaluated_at: datetime,
    ) -> PaperAcceptanceReport:
        metrics = self.journal.snapshot(period_start=period_start, period_end=period_end)
        policy = self.policy
        checks = (
            AcceptanceCheck(
                "minimum_sessions",
                metrics.session_count >= policy.min_sessions,
                str(metrics.session_count),
                f">={policy.min_sessions}",
            ),
            AcceptanceCheck(
                "minimum_reconciliations",
                metrics.reconciliation_count >= policy.min_reconciliations,
                str(metrics.reconciliation_count),
                f">={policy.min_reconciliations}",
            ),
            AcceptanceCheck(
                "rejected_order_rate",
                metrics.rejected_order_rate <= policy.max_rejected_order_rate,
                f"{metrics.rejected_order_rate:.8f}",
                f"<={policy.max_rejected_order_rate:.8f}",
            ),
            AcceptanceCheck(
                "critical_reconciliation_rate",
                metrics.critical_reconciliation_rate <= policy.max_critical_reconciliation_rate,
                f"{metrics.critical_reconciliation_rate:.8f}",
                f"<={policy.max_critical_reconciliation_rate:.8f}",
            ),
            AcceptanceCheck(
                "kill_switch_trips",
                metrics.kill_switch_trip_count <= policy.max_kill_switch_trips,
                str(metrics.kill_switch_trip_count),
                f"<={policy.max_kill_switch_trips}",
            ),
            AcceptanceCheck(
                "restart_recovery_drills",
                metrics.restart_recovery_drill_count >= policy.min_restart_recovery_drills
                and metrics.restart_recovery_pass_count == metrics.restart_recovery_drill_count,
                f"{metrics.restart_recovery_pass_count}/{metrics.restart_recovery_drill_count}",
                f">={policy.min_restart_recovery_drills} drills and 100% pass",
            ),
            AcceptanceCheck(
                "kill_switch_drills",
                metrics.kill_switch_drill_count >= policy.min_kill_switch_drills
                and metrics.kill_switch_drill_pass_count == metrics.kill_switch_drill_count,
                f"{metrics.kill_switch_drill_pass_count}/{metrics.kill_switch_drill_count}",
                f">={policy.min_kill_switch_drills} drills and 100% pass",
            ),
            AcceptanceCheck(
                "critical_incidents",
                metrics.critical_incident_count <= policy.max_critical_incidents,
                str(metrics.critical_incident_count),
                f"<={policy.max_critical_incidents}",
            ),
            AcceptanceCheck(
                "idempotency_failures",
                metrics.idempotency_failure_count <= policy.max_idempotency_failures,
                str(metrics.idempotency_failure_count),
                f"<={policy.max_idempotency_failures}",
            ),
        )
        evaluated = require_aware_datetime(evaluated_at, "evaluated_at")
        identity = "|".join((policy.policy_id, policy.version, metrics.digest, evaluated.isoformat()))
        report = PaperAcceptanceReport(
            report_id=f"paper-acceptance-{hashlib.sha256(identity.encode()).hexdigest()[:24]}",
            policy_id=policy.policy_id,
            policy_version=policy.version,
            evaluated_at=evaluated,
            metrics=metrics,
            checks=checks,
        )
        self.evidence_store.register_acceptance_report(report)
        return report
