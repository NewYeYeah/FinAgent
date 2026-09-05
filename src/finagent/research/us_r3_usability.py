"""Bounded, label-blind engineering acceptance for the three frozen R3 prototypes.

This operator deliberately cannot evaluate returns, select candidates or run an
Alpha Gate. Reused R2 data provides input/numerical usability evidence only.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from collections import Counter
from collections.abc import Callable, Iterator, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from finagent.research.us_a1_factor_materialization import compile_factor_graph_batch
from finagent.research.us_a1_factor_panel_materialization import (
    FactorPanelAsset,
    materialize_compiled_factor_panel,
)
from finagent.research.us_baselines import USBaselineBar
from finagent.research.us_r3_alpha_catalog import build_us_r3_executable_frontier_candidates

Progress = Callable[[str, Mapping[str, object]], None]
SLICE_ID = "decay_15m_30m"
MAXIMUM_SESSION_ROWS = 256 * 64
FETCH_ROWS = 512

# Explicit projection: no forward prices, labels or label availability enter
# the feature process. The slice is an input view, not a response-horizon choice.
FEATURE_QUERY = """
SELECT CAST(session_date AS VARCHAR), session_id, research_asset_id,
       epoch(event_time), epoch(available_at), open, high, low, close, volume,
       is_complete, signal_interval
FROM read_parquet(?) WHERE slice_id = ?
ORDER BY session_date, research_asset_id, event_time
"""


def _render(payload: object) -> bytes:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def _digest(payload: object) -> str:
    return hashlib.sha256(_render(payload)).hexdigest()


def _file_sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def implementation_identity() -> str:
    """Bind the actual numerical/operator sources, not only graph identities."""
    root = Path(__file__).parent
    names = (
        "us_r3_usability.py",
        "us_a1_factor_panel_materialization.py",
        "us_a1_factor_materialization.py",
        "us_r3_alpha_catalog.py",
    )
    return _digest({name: _file_sha256(root / name) for name in names})


def write_immutable_json(path: Path, payload: Mapping[str, object]) -> None:
    """Publish a complete file without replacing an existing evidence artifact."""
    encoded = _render(payload) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != encoded:
            raise ValueError(f"immutable evidence mismatch: {path}")
        return
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".r3-", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.read_bytes() != encoded:
                raise ValueError(f"immutable evidence mismatch: {path}") from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _read_evidence(path: Path, binding: Mapping[str, object]) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"evidence must be an object: {path}")
    evidence_id = payload.get("evidence_id")
    content = {key: value for key, value in payload.items() if key != "evidence_id"}
    if evidence_id != "us-r3-usability-year-" + _digest(content):
        raise ValueError(f"evidence content identity mismatch: {path}")
    if payload.get("binding") != dict(binding):
        raise ValueError(f"evidence source/implementation binding mismatch: {path}")
    return cast(dict[str, Any], payload)


def _session_assets(rows: list[tuple[Any, ...]]) -> tuple[FactorPanelAsset, ...]:
    by_asset: dict[str, list[USBaselineBar]] = {}
    sessions: set[str] = set()
    for row in rows:
        (
            _,
            session,
            asset,
            event,
            available,
            opening,
            high,
            low,
            close,
            volume,
            complete,
            interval,
        ) = row
        if (
            not isinstance(asset, str)
            or not isinstance(session, str)
            or not isinstance(complete, bool)
        ):
            raise TypeError("invalid feature identity/completeness types")
        if interval != "15m":
            raise ValueError("feature slice must carry the frozen 15m interval")
        sessions.add(session)
        by_asset.setdefault(asset, []).append(
            USBaselineBar(
                event_time=datetime.fromtimestamp(event, UTC),
                available_at=datetime.fromtimestamp(available, UTC),
                session_id=session,
                open=opening,
                high=high,
                low=low,
                close=close,
                volume=volume,
                is_complete=complete,
            )
        )
    if len(sessions) != 1:
        raise ValueError("one session date must bind exactly one session ID")
    if len(by_asset) > 256:
        raise ValueError("session asset bound exceeded")
    observed = sorted({bar.event_time for bars in by_asset.values() for bar in bars})
    count = int((observed[-1] - observed[0]).total_seconds() // 900) + 1
    if count > 64:
        raise ValueError("session clock bound exceeded before alignment")
    clocks = tuple(observed[0] + timedelta(minutes=15 * index) for index in range(count))
    if not set(observed).issubset(clocks):
        raise ValueError("source clocks must align to a 15m grid")
    assets = []
    for asset, bars in sorted(by_asset.items()):
        by_clock = {bar.event_time: bar for bar in bars}
        if len(by_clock) != len(bars):
            raise ValueError("duplicate asset/session clock is not silently collapsed")
        aligned = []
        for clock in clocks:
            if clock in by_clock:
                aligned.append(by_clock[clock])
            else:
                # Structural padding ONLY. is_complete=False is applied at
                # every node before consumers. These sentinel numbers are not
                # observed/imputed prices and never become a usable feature.
                aligned.append(
                    USBaselineBar(
                        event_time=clock,
                        available_at=clock + timedelta(minutes=15),
                        session_id=bars[0].session_id,
                        open=1.0,
                        high=1.0,
                        low=1.0,
                        close=1.0,
                        volume=0.0,
                        is_complete=False,
                    )
                )
        assets.append(FactorPanelAsset(asset, tuple(aligned)))
    return tuple(assets)


def iter_feature_sessions(source: Path) -> Iterator[tuple[str, tuple[FactorPanelAsset, ...], int]]:
    import duckdb

    # Close database handles before removing the task-owned spill directory,
    # including when a consumer aborts this generator on Windows.
    with tempfile.TemporaryDirectory(prefix="finagent-r3-") as spill:
        connection = duckdb.connect(config={"memory_limit": "256MiB", "threads": "1"})
        try:
            connection.execute("SET temp_directory = ?", [spill])
            connection.execute("SET max_temp_directory_size = '1GiB'")
            connection.execute(FEATURE_QUERY, [str(source), SLICE_ID])
            current: str | None = None
            rows: list[tuple[Any, ...]] = []
            while batch := connection.fetchmany(FETCH_ROWS):
                for row in batch:
                    session_date = row[0]
                    if not isinstance(session_date, str):
                        raise TypeError("session_date must be present")
                    if current is not None and session_date != current:
                        yield current, _session_assets(rows), len(rows)
                        rows = []
                    current = session_date
                    if len(rows) >= MAXIMUM_SESSION_ROWS:
                        raise ValueError("session row bound exceeded before panel allocation")
                    rows.append(row)
            if current is not None:
                yield current, _session_assets(rows), len(rows)
        finally:
            connection.close()


def reference_signals(
    assets: tuple[FactorPanelAsset, ...],
    minimum_cross_section: int,
) -> dict[str, list[tuple[float | None, ...]]]:
    """Independent direct-formula oracle; does not use graph execution helpers.

    Applies the same frozen complete-case windows, Type-7 winsorization and
    population normalization. Used only for numeric parity, never prediction.
    """
    output: dict[str, list[tuple[float | None, ...]]] = {asset.asset_id: [] for asset in assets}
    if not assets or not assets[0].bars:
        raise ValueError("reference requires a nonempty session")
    if any(
        bar.session_id != assets[0].bars[0].session_id for asset in assets for bar in asset.bars
    ):
        raise ValueError("reference evaluates exactly one session")
    for index in range(len(assets[0].bars)):
        raw: list[dict[str, float]] = [{}, {}, {}]
        for asset in assets:
            bars = asset.bars
            if index >= 8 and all(bar.is_complete for bar in bars[index - 8 : index + 1]):
                returns = [
                    bars[j].close / bars[j - 1].close - 1.0 for j in range(index - 7, index + 1)
                ]
                average = sum(returns) / 8
                volatility = math.sqrt(sum((value - average) ** 2 for value in returns) / 8)
                if volatility > 1e-12:
                    raw[0][asset.asset_id] = (
                        bars[index].close / bars[index - 3].close - 1
                    ) / volatility
            if index >= 7 and all(bar.is_complete for bar in bars[index - 7 : index + 1]):
                window = bars[index - 7 : index + 1]
                mean_volume = sum(bar.volume for bar in window) / 8
                if mean_volume <= 1e-12:
                    continue
                relative_volume = bars[index].volume / mean_volume
                raw[1][asset.asset_id] = (
                    -(bars[index].close / bars[index - 2].close - 1) * relative_volume
                )
                high = max(bar.high for bar in window)
                low = min(bar.low for bar in window)
                if high - low > 1e-12:
                    raw[2][asset.asset_id] = (
                        (bars[index].close - low) / (high - low) - 0.5
                    ) * relative_volume
        normalized: list[dict[str, float]] = []
        for candidate_index, values in enumerate(raw):
            if len(values) < minimum_cross_section:
                normalized.append({})
                continue
            ordered = sorted(values.values())
            bounds = []
            for quantile in (0.05, 0.95):
                position = (len(ordered) - 1) * quantile
                lower, upper = math.floor(position), math.ceil(position)
                weight = position - lower
                bounds.append(ordered[lower] * (1 - weight) + ordered[upper] * weight)
            clipped = {
                asset: min(bounds[1], max(bounds[0], value)) for asset, value in values.items()
            }
            if candidate_index == 1:
                ranked = sorted(clipped.values())
                normalized.append(
                    {
                        asset: (ranked.index(value) + ranked.count(value) / 2 - 0.5)
                        / (len(ranked) - 1)
                        for asset, value in clipped.items()
                    }
                )
            else:
                average = math.fsum(clipped.values()) / len(clipped)
                variance = math.fsum((value - average) ** 2 for value in clipped.values()) / len(
                    clipped
                )
                normalized.append(
                    {
                        asset: (value - average) / math.sqrt(variance)
                        for asset, value in clipped.items()
                    }
                    if variance > 0
                    else {}
                )
        for asset in assets:
            output[asset.asset_id].append(
                tuple(values.get(asset.asset_id) for values in normalized)
            )
    return output


def run_usability(
    sources: tuple[Path, ...],
    output_root: Path,
    *,
    minimum_cross_section: int = 3,
    progress: Progress | None = None,
) -> dict[str, object]:
    if (
        not sources
        or len(sources) > 100
        or len({path.resolve() for path in sources}) != len(sources)
    ):
        raise ValueError("require 1..100 unique annual sources")
    if not 2 <= minimum_cross_section <= 256:
        raise ValueError("minimum_cross_section must be 2..256")
    candidates = build_us_r3_executable_frontier_candidates()
    candidate_ids = tuple(item.candidate_id for item in candidates)
    compiled = compile_factor_graph_batch(
        tuple(item.graph for item in candidates), admit_panel_operators=True
    )
    implementation = implementation_identity()
    hashed_sources: list[tuple[Path, str]] = []
    for source in sources:
        if progress:
            progress("source_hash", {"source": str(source)})
        hashed_sources.append((source, _file_sha256(source)))
    write_immutable_json(
        output_root / "us_r3_feature_usability_plan.json",
        {
            "schema_version": "finagent.us-r3-feature-usability-plan.v1",
            "source_sha256": [digest for _, digest in hashed_sources],
            "implementation_sha256": implementation,
            "candidate_ids": candidate_ids,
            "minimum_cross_section": minimum_cross_section,
            "authority": "engineering_feature_usability_only",
        },
    )
    annual: list[dict[str, Any]] = []
    resumed = 0
    for source, source_hash in hashed_sources:
        if progress:
            progress("source_start", {"source": str(source)})
        binding: dict[str, object] = {
            "source_sha256": source_hash,
            "implementation_sha256": implementation,
            "slice_id": SLICE_ID,
            "compiled_batch_id": compiled.batch_id,
            "candidate_ids": list(candidate_ids),
            "minimum_cross_section": minimum_cross_section,
            "maximum_session_rows": MAXIMUM_SESSION_ROWS,
            "fetch_rows": FETCH_ROWS,
            "reference_absolute_tolerance": 1e-10,
            "reference_relative_tolerance": 1e-10,
        }
        path = output_root / ("source_" + source_hash + ".json")
        if path.exists():
            report = _read_evidence(path, binding)
            resumed += 1
            if progress:
                progress(
                    "source_resumed", {"source": str(source), "evidence_id": report["evidence_id"]}
                )
            annual.append(report)
            continue
        counts: Counter[str] = Counter()
        reasons: Counter[str] = Counter()
        feature_digest = hashlib.sha256()
        session_count = row_count = peak_rows = missing_rows = 0
        maximum_difference = 0.0
        for session_date, assets, observed_row_count in iter_feature_sessions(source):
            if progress:
                progress("session_start", {"source": str(source), "session_date": session_date})
            result = materialize_compiled_factor_panel(
                compiled, assets, minimum_cross_section=minimum_cross_section
            )
            reference = reference_signals(assets, minimum_cross_section)
            for item in result.candidates:
                candidate_index = candidate_ids.index(item.candidate_id)
                for index, value in enumerate(item.values):
                    expected = reference[item.asset_id][index][candidate_index]
                    if (value is None) != (expected is None):
                        raise ValueError(
                            f"reference availability mismatch: {session_date}/{item.asset_id}/{item.candidate_id}/{index}"
                        )
                    if value is not None and expected is not None:
                        if not math.isclose(value, expected, abs_tol=1e-10, rel_tol=1e-10):
                            raise ValueError(
                                f"reference numeric mismatch: {session_date}/{item.asset_id}/{item.candidate_id}/{index}"
                            )
                        maximum_difference = max(maximum_difference, abs(value - expected))
                        counts[item.candidate_id] += 1
                    else:
                        reasons[str(item.unavailable_reasons[index])] += 1
                feature_digest.update(
                    _render(
                        [
                            session_date,
                            item.asset_id,
                            item.candidate_id,
                            item.values,
                            item.unavailable_reasons,
                        ]
                    )
                )
            current_rows = len(assets) * len(assets[0].bars)
            row_count += observed_row_count
            missing_rows += current_rows - observed_row_count
            peak_rows = max(peak_rows, current_rows)
            session_count += 1
        if _file_sha256(source) != source_hash:
            raise ValueError(f"source mutated during evaluation: {source}")
        report = {
            "schema_version": "finagent.us-r3-feature-usability.v1",
            "binding": binding,
            "session_count": session_count,
            "row_count": row_count,
            "missing_bar_padding_count": missing_rows,
            "peak_session_rows": peak_rows,
            "candidate_available_counts": {
                candidate: counts[candidate] for candidate in candidate_ids
            },
            "unavailable_reason_counts": dict(sorted(reasons.items())),
            "feature_digest": feature_digest.hexdigest(),
            "reference_parity_passed": True,
            "maximum_reference_absolute_difference": maximum_difference,
            "passed": session_count > 0
            and all(counts[candidate] > 0 for candidate in candidate_ids),
            "authority": "engineering_feature_usability_only",
            "labels_read": False,
            "financial_performance_evaluated": False,
            "alpha_gate_evaluated": False,
            "alpha_authority": False,
            "mt5_accessed": False,
            "external_model_called": False,
        }
        report["evidence_id"] = "us-r3-usability-year-" + _digest(report)
        write_immutable_json(path, report)
        annual.append(report)
        if progress:
            progress(
                "source_complete",
                {
                    "source": str(source),
                    "session_count": session_count,
                    "evidence_id": report["evidence_id"],
                    "passed": report["passed"],
                },
            )
    summary: dict[str, object] = {
        "schema_version": "finagent.us-r3-feature-usability-batch.v1",
        "annual_evidence_ids": [item["evidence_id"] for item in annual],
        "source_count": len(annual),
        "session_count": sum(item["session_count"] for item in annual),
        "row_count": sum(item["row_count"] for item in annual),
        "missing_bar_padding_count": sum(item["missing_bar_padding_count"] for item in annual),
        "peak_session_rows": max(item["peak_session_rows"] for item in annual),
        "passed": all(item["passed"] for item in annual),
        "reference_parity_passed": True,
        "candidate_count": len(candidate_ids),
        "authority": "engineering_feature_usability_only",
        "labels_read": False,
        "financial_performance_evaluated": False,
        "alpha_gate_evaluated": False,
        "alpha_authority": False,
        "mt5_accessed": False,
        "external_model_called": False,
    }
    summary["evidence_id"] = "us-r3-usability-batch-" + _digest(summary)
    write_immutable_json(output_root / "us_r3_feature_usability.json", summary)
    return {
        **summary,
        "resumed_source_count": resumed,
        "evaluated_source_count": len(annual) - resumed,
    }
