from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence


@dataclass(frozen=True, slots=True)
class StoredFeatureView:
    feature_digest: str
    feature_id: str
    source: str
    generated_at: str
    spec: Mapping[str, Any]
    validation: Mapping[str, Any]
    generator_id: str
    smoke_output_digest: str
    metadata: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "spec", MappingProxyType(dict(self.spec)))
        object.__setattr__(self, "validation", MappingProxyType(dict(self.validation)))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


def load_feature_store(
    path: str | Path,
    *,
    digests: Sequence[str] | None = None,
) -> dict[str, StoredFeatureView]:
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    connection = sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)
    try:
        requested = tuple(dict.fromkeys(str(value) for value in (digests or ())))
        if requested:
            placeholders = ",".join("?" for _ in requested)
            rows = connection.execute(
                "SELECT digest, feature_id, source, payload_json, generated_at "
                f"FROM generated_features WHERE digest IN ({placeholders}) "
                "ORDER BY generated_at, digest",
                requested,
            ).fetchall()
        else:
            rows = connection.execute(
                "SELECT digest, feature_id, source, payload_json, generated_at "
                "FROM generated_features ORDER BY generated_at, digest"
            ).fetchall()
    finally:
        connection.close()

    output: dict[str, StoredFeatureView] = {}
    for digest, feature_id, code, payload_json, generated_at in rows:
        payload = json.loads(payload_json)
        if not isinstance(payload, Mapping):
            continue
        spec = payload.get("spec", {})
        validation = payload.get("validation", {})
        metadata = payload.get("metadata", {})
        output[str(digest)] = StoredFeatureView(
            feature_digest=str(digest),
            feature_id=str(feature_id),
            source=str(code),
            generated_at=str(generated_at),
            spec=spec if isinstance(spec, Mapping) else {},
            validation=validation if isinstance(validation, Mapping) else {},
            generator_id=str(payload.get("generator_id", "")),
            smoke_output_digest=str(payload.get("smoke_output_digest", "")),
            metadata=metadata if isinstance(metadata, Mapping) else {},
        )
    return output
