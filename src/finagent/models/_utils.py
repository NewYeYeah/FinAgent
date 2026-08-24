from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from typing import Any

from finagent.domain.experiments import ArtifactRef, ArtifactType
from finagent.domain.research import ResearchSplit


def infer_horizon(split: ResearchSplit) -> timedelta:
    if len(split.timestamps) < 2:
        return timedelta(days=1)
    deltas = [
        (right - left).total_seconds()
        for left, right in zip(split.timestamps, split.timestamps[1:])
        if right > left
    ]
    if not deltas:
        return timedelta(days=1)
    deltas.sort()
    seconds = deltas[len(deltas) // 2]
    return timedelta(seconds=max(seconds, 1.0))


def model_artifact(name: str, dataset_digest: str, payload: dict[str, Any]) -> ArtifactRef:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    digest = hashlib.sha256((dataset_digest + "|" + canonical).encode("utf-8")).hexdigest()
    return ArtifactRef(
        artifact_id=f"model:{name}",
        artifact_type=ArtifactType.MODEL,
        version="phase1",
        digest=digest,
        uri=f"memory://models/{name}/{digest[:16]}",
    )
