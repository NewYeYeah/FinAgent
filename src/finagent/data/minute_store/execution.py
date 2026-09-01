from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from finagent.domain._validation import require_non_empty

_MEMORY_LIMIT_RE = re.compile(r"^[1-9][0-9]*(?:\.[0-9]+)?(?:KB|MB|GB|TB|KiB|MiB|GiB|TiB)$")


def _canonical_hash(payload: dict[str, object], *, prefix: str) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:24]}"


def _sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


@dataclass(frozen=True, slots=True)
class DuckDBExecutionPolicy:
    """Engine-resource bounds for out-of-core minute queries.

    Local directory paths are deliberately excluded from policy identity. The policy
    binds whether temporary spill is allowed, not where one workstation stores it.
    """

    memory_limit: str = "512MB"
    threads: int = 2
    allow_temp_spill: bool = True
    preserve_insertion_order: bool = False
    schema_version: str = "finagent.duckdb-execution-policy.v1"

    def __post_init__(self) -> None:
        memory_limit = require_non_empty(self.memory_limit, "memory_limit")
        if _MEMORY_LIMIT_RE.fullmatch(memory_limit) is None:
            raise ValueError(
                "memory_limit must be a positive DuckDB size such as 256MB, 1GB or 2GiB"
            )
        if not 1 <= self.threads <= 32:
            raise ValueError("threads must be in 1..32")
        object.__setattr__(self, "memory_limit", memory_limit)

    @property
    def policy_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="duckdb-execution-policy")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "memory_limit": self.memory_limit,
            "threads": self.threads,
            "allow_temp_spill": self.allow_temp_spill,
            "preserve_insertion_order": self.preserve_insertion_order,
        }
        if include_id:
            payload["policy_id"] = self.policy_id
        return payload


DEFAULT_DUCKDB_EXECUTION_POLICY = DuckDBExecutionPolicy()


@dataclass(frozen=True, slots=True)
class DuckDBExecutionSettings:
    policy_id: str
    observed_memory_limit: str
    observed_threads: int
    observed_preserve_insertion_order: bool
    temp_spill_enabled: bool
    schema_version: str = "finagent.duckdb-execution-settings.v1"

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "policy_id": self.policy_id,
            "observed_memory_limit": self.observed_memory_limit,
            "observed_threads": self.observed_threads,
            "observed_preserve_insertion_order": self.observed_preserve_insertion_order,
            "temp_spill_enabled": self.temp_spill_enabled,
        }


def configure_duckdb_connection(
    connection: Any,
    policy: DuckDBExecutionPolicy = DEFAULT_DUCKDB_EXECUTION_POLICY,
    *,
    temp_directory: str | Path | None = None,
) -> DuckDBExecutionSettings:
    """Apply and read back the resource policy on one DuckDB connection."""

    connection.execute(f"SET memory_limit = {_sql_string(policy.memory_limit)}")
    connection.execute(f"SET threads = {policy.threads}")
    connection.execute(
        "SET preserve_insertion_order = "
        + ("true" if policy.preserve_insertion_order else "false")
    )

    spill_enabled = policy.allow_temp_spill
    if temp_directory is not None:
        if not policy.allow_temp_spill:
            raise ValueError("temp_directory supplied while allow_temp_spill=false")
        directory = Path(temp_directory).expanduser().resolve()
        directory.mkdir(parents=True, exist_ok=True)
        connection.execute(f"SET temp_directory = {_sql_string(directory.as_posix())}")

    memory_row = connection.execute("SELECT current_setting('memory_limit')").fetchone()
    threads_row = connection.execute("SELECT current_setting('threads')").fetchone()
    insertion_row = connection.execute(
        "SELECT current_setting('preserve_insertion_order')"
    ).fetchone()
    if memory_row is None or threads_row is None or insertion_row is None:
        raise RuntimeError("DuckDB execution settings could not be read back")

    return DuckDBExecutionSettings(
        policy_id=policy.policy_id,
        observed_memory_limit=str(memory_row[0]),
        observed_threads=int(threads_row[0]),
        observed_preserve_insertion_order=bool(insertion_row[0]),
        temp_spill_enabled=spill_enabled,
    )
