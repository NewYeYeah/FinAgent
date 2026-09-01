from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime

from .execution import DuckDBExecutionPolicy, DuckDBExecutionSettings
from .materialize import MinuteMaterialization
from .query import MinuteQueryPlan


def _canonical_hash(payload: dict[str, object], *, prefix: str) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:24]}"


@dataclass(frozen=True, slots=True)
class MinuteStoreSmokePolicy:
    minimum_assets: int = 4
    minimum_partitions: int = 2
    require_materialization: bool = True
    require_replay_match: bool = True
    schema_version: str = "finagent.minute-store-smoke-policy.v1"

    def __post_init__(self) -> None:
        if self.minimum_assets < 1 or self.minimum_partitions < 1:
            raise ValueError("smoke policy minimums must be >= 1")

    @property
    def policy_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="minute-store-smoke-policy")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "minimum_assets": self.minimum_assets,
            "minimum_partitions": self.minimum_partitions,
            "require_materialization": self.require_materialization,
            "require_replay_match": self.require_replay_match,
        }
        if include_id:
            payload["policy_id"] = self.policy_id
        return payload


DEFAULT_MINUTE_STORE_SMOKE_POLICY = MinuteStoreSmokePolicy()


@dataclass(frozen=True, slots=True)
class MinuteStoreSmokeReport:
    plan: MinuteQueryPlan
    smoke_policy: MinuteStoreSmokePolicy
    execution_policy: DuckDBExecutionPolicy
    execution_settings: DuckDBExecutionSettings
    actual_rows: int
    primary_materialization: MinuteMaterialization | None
    replay_materialization: MinuteMaterialization | None
    replay_match: bool | None
    ran_at: datetime
    schema_version: str = "finagent.minute-store-smoke-report.v2"

    def __post_init__(self) -> None:
        if self.actual_rows < 0:
            raise ValueError("actual_rows must be >= 0")
        if self.ran_at.tzinfo is None or self.ran_at.utcoffset() is None:
            raise ValueError("ran_at must be timezone-aware")
        if self.execution_settings.policy_id != self.execution_policy.policy_id:
            raise ValueError("execution settings do not bind the supplied execution policy")
        if self.execution_settings.observed_threads != self.execution_policy.threads:
            raise ValueError("observed DuckDB thread count does not match execution policy")
        if (
            self.execution_settings.observed_preserve_insertion_order
            != self.execution_policy.preserve_insertion_order
        ):
            raise ValueError("observed insertion-order policy does not match execution policy")
        if self.execution_settings.temp_spill_enabled != self.execution_policy.allow_temp_spill:
            raise ValueError("observed temp-spill state does not match execution policy")
        if self.primary_materialization is not None:
            if self.primary_materialization.plan_id != self.plan.plan_id:
                raise ValueError("primary materialization does not bind the smoke plan")
            if self.primary_materialization.row_count != self.actual_rows:
                raise ValueError("primary materialization row count does not match smoke rows")
        if self.replay_materialization is not None:
            if self.replay_materialization.plan_id != self.plan.plan_id:
                raise ValueError("replay materialization does not bind the smoke plan")
            if self.replay_materialization.row_count != self.actual_rows:
                raise ValueError("replay materialization row count does not match smoke rows")

    @property
    def blockers(self) -> tuple[str, ...]:
        blockers: list[str] = []
        if len(self.plan.query.assets) < self.smoke_policy.minimum_assets:
            blockers.append("query:insufficient_assets")
        if len(self.plan.partition_months) < self.smoke_policy.minimum_partitions:
            blockers.append("query:insufficient_partitions")
        if self.actual_rows <= 0:
            blockers.append("query:no_rows")
        if self.smoke_policy.require_materialization and self.primary_materialization is None:
            blockers.append("materialization:missing")
        if self.smoke_policy.require_replay_match and self.replay_match is not True:
            blockers.append("replay:not_verified_or_mismatch")
        return tuple(blockers)

    @property
    def passed(self) -> bool:
        return not self.blockers

    @property
    def report_id(self) -> str:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "plan_id": self.plan.plan_id,
            "smoke_policy_id": self.smoke_policy.policy_id,
            "execution_policy_id": self.execution_policy.policy_id,
            "execution_settings": self.execution_settings.to_dict(),
            "actual_rows": self.actual_rows,
            "primary_materialization_id": (
                self.primary_materialization.materialization_id
                if self.primary_materialization is not None
                else None
            ),
            "replay_materialization_id": (
                self.replay_materialization.materialization_id
                if self.replay_materialization is not None
                else None
            ),
            "replay_match": self.replay_match,
            "passed": self.passed,
            "blockers": list(self.blockers),
        }
        return _canonical_hash(payload, prefix="minute-store-smoke")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "report_id": self.report_id,
            "ran_at": self.ran_at.astimezone(UTC).isoformat(),
            "passed": self.passed,
            "blockers": list(self.blockers),
            "smoke_policy": self.smoke_policy.to_dict(),
            "execution_policy": self.execution_policy.to_dict(),
            "execution_settings": self.execution_settings.to_dict(),
            "query": self.plan.query.to_dict(),
            "plan": self.plan.to_dict(),
            "asset_count": len(self.plan.query.assets),
            "partition_count": len(self.plan.partition_months),
            "actual_rows": self.actual_rows,
            "primary_materialization": (
                self.primary_materialization.to_dict()
                if self.primary_materialization is not None
                else None
            ),
            "replay_materialization": (
                self.replay_materialization.to_dict()
                if self.replay_materialization is not None
                else None
            ),
            "replay_match": self.replay_match,
        }
