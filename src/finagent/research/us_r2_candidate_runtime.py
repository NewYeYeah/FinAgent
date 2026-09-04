from __future__ import annotations

from collections.abc import Mapping, Sequence

from finagent.research.us_r2_candidate_cache import (
    USR2AssetCandidateCache,
    USR2CandidateExecution,
    materialize_us_r2_asset_candidate_cache as _materialize_candidate_cache,
)


def _normalize_r1_incomplete_current_bar_labels(
    rows: Sequence[Mapping[str, object]],
) -> tuple[Mapping[str, object], ...]:
    """Make label fields non-authoritative for incomplete current bars, as in US-R1.

    The accepted US-R1 materializer appends every bar to feature history, then skips an
    incomplete current bar before validating any label anchor. Annual R2 base panels retain
    label columns for every bar, so the candidate cache must not accidentally promote those
    columns into an extra validation gate for a formation that R1 would never emit.
    """

    normalized: list[Mapping[str, object]] = []
    for raw in rows:
        if raw.get("is_complete") is False:
            row = dict(raw)
            row["label_available"] = False
            row["label_value"] = None
            row["target_available_at"] = None
            row["unavailable_reason"] = "target_crosses_session"
            normalized.append(row)
        else:
            normalized.append(raw)
    return tuple(normalized)


def materialize_us_r2_asset_candidate_cache_r1_compatible(
    rows: Sequence[Mapping[str, object]],
    execution: USR2CandidateExecution,
    *,
    expected_asset: str,
) -> USR2AssetCandidateCache:
    return _materialize_candidate_cache(
        _normalize_r1_incomplete_current_bar_labels(rows),
        execution,
        expected_asset=expected_asset,
    )
