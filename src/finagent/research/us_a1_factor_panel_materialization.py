from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from finagent.research.us_a1_factor_graph import FactorOperator
from finagent.research.us_a1_factor_materialization import (
    CompiledFactorBatch,
    CompiledFactorNode,
    _evaluate_node_series,
    _validate_bars,
)
from finagent.research.us_baselines import USBaselineBar


class PanelFactorUnavailableReason(StrEnum):
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
    CROSS_SESSION_WINDOW = "CROSS_SESSION_WINDOW"
    INCOMPLETE_BAR = "INCOMPLETE_BAR"
    INSUFFICIENT_CROSS_SECTION = "INSUFFICIENT_CROSS_SECTION"
    ZERO_CROSS_SECTION_DISPERSION = "ZERO_CROSS_SECTION_DISPERSION"
    REGIME_EXCLUDED = "REGIME_EXCLUDED"
    NUMERIC_UNAVAILABLE = "NUMERIC_UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class FactorPanelAsset:
    asset_id: str
    bars: tuple[USBaselineBar, ...]

    def __post_init__(self) -> None:
        if not self.asset_id.strip():
            raise ValueError("panel asset_id must be non-empty")


@dataclass(frozen=True, slots=True)
class FactorPanelRegimeMask:
    policy_id: str
    labels: tuple[str, ...]
    source_evidence_id: str | None = None
    label_available_at: tuple[datetime, ...] = ()
    schema_version: str = "finagent.us-a1-factor-panel-regime-mask.v2"

    def __post_init__(self) -> None:
        if not self.policy_id.strip():
            raise ValueError("regime mask policy_id must be non-empty")
        if not self.labels or any(not item.strip() for item in self.labels):
            raise ValueError("regime mask labels must be non-empty")
        if self.label_available_at and len(self.label_available_at) != len(self.labels):
            raise ValueError("regime availability timestamps must align with labels")
        if any(item.tzinfo is None or item.utcoffset() is None for item in self.label_available_at):
            raise ValueError("regime availability timestamps must be timezone-aware")


@dataclass(frozen=True, slots=True)
class PanelFactorCandidateSeries:
    asset_id: str
    candidate_id: str
    values: tuple[float | None, ...]
    unavailable_reasons: tuple[PanelFactorUnavailableReason | None, ...]
    lookback_bars: int
    schema_version: str = "finagent.us-a1-panel-factor-candidate-series.v1"

    def __post_init__(self) -> None:
        if not self.asset_id.strip() or not self.candidate_id.strip():
            raise ValueError("panel candidate identities must be non-empty")
        if len(self.values) != len(self.unavailable_reasons):
            raise ValueError("panel candidate values/reasons length mismatch")
        for value, reason in zip(self.values, self.unavailable_reasons, strict=True):
            if (value is None) == (reason is None):
                raise ValueError("exactly one of panel candidate value/reason must be set")
            if value is not None and not math.isfinite(value):
                raise ValueError("panel candidate values must be finite")


@dataclass(frozen=True, slots=True)
class FactorPanelMaterialization:
    compiled_batch_id: str
    asset_count: int
    bar_count_per_asset: int
    minimum_cross_section: int
    node_series_evaluation_count: int
    candidates: tuple[PanelFactorCandidateSeries, ...]
    schema_version: str = "finagent.us-a1-factor-panel-materialization.v2"

    def __post_init__(self) -> None:
        if min(self.asset_count, self.bar_count_per_asset, self.minimum_cross_section) < 1:
            raise ValueError("panel materialization counts must be positive")
        if self.node_series_evaluation_count < 1:
            raise ValueError("panel materialization must evaluate at least one node series")
        expected = self.asset_count * len({item.candidate_id for item in self.candidates})
        if len(self.candidates) != expected:
            raise ValueError("panel materialization must contain every asset/candidate pair")


_PANEL_OPERATORS = frozenset(
    {
        FactorOperator.CROSS_SECTION_RANK,
        FactorOperator.CROSS_SECTION_ZSCORE,
        FactorOperator.WINSORIZE,
    }
)


def _type7_quantile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _average_percentile_ranks(values: list[tuple[str, float]]) -> dict[str, float]:
    ordered = sorted(values, key=lambda item: (item[1], item[0]))
    denominator = len(ordered) - 1
    result: dict[str, float] = {}
    start = 0
    while start < len(ordered):
        end = start + 1
        while end < len(ordered) and ordered[end][1] == ordered[start][1]:
            end += 1
        average_zero_based_rank = (start + end - 1) / 2.0
        percentile = average_zero_based_rank / denominator
        for asset_id, _ in ordered[start:end]:
            result[asset_id] = percentile
        start = end
    return result


def _panel_transform(
    node: CompiledFactorNode,
    source_by_asset: dict[str, list[float | None]],
    *,
    bar_count: int,
    minimum_cross_section: int,
) -> tuple[
    dict[str, list[float | None]],
    dict[str, list[PanelFactorUnavailableReason | None]],
]:
    values_by_asset: dict[str, list[float | None]] = {
        asset_id: [None for _ in range(bar_count)] for asset_id in source_by_asset
    }
    reasons_by_asset: dict[str, list[PanelFactorUnavailableReason | None]] = {
        asset_id: [None] * bar_count for asset_id in source_by_asset
    }
    for index in range(bar_count):
        available: list[tuple[str, float]] = []
        for asset_id, asset_series in source_by_asset.items():
            value = asset_series[index]
            if value is not None:
                available.append((asset_id, value))
        available.sort(key=lambda item: item[0])
        if len(available) < minimum_cross_section:
            for asset_id in source_by_asset:
                reasons_by_asset[asset_id][index] = (
                    PanelFactorUnavailableReason.INSUFFICIENT_CROSS_SECTION
                )
            continue
        if node.operator is FactorOperator.CROSS_SECTION_RANK:
            transformed = _average_percentile_ranks(available)
        elif node.operator is FactorOperator.CROSS_SECTION_ZSCORE:
            if min(value for _, value in available) == max(value for _, value in available):
                for asset_id in source_by_asset:
                    reasons_by_asset[asset_id][index] = (
                        PanelFactorUnavailableReason.ZERO_CROSS_SECTION_DISPERSION
                    )
                continue
            mean_value = math.fsum(value for _, value in available) / len(available)
            variance = math.fsum((value - mean_value) ** 2 for _, value in available) / len(
                available
            )
            if variance <= 0.0:
                for asset_id in source_by_asset:
                    reasons_by_asset[asset_id][index] = (
                        PanelFactorUnavailableReason.ZERO_CROSS_SECTION_DISPERSION
                    )
                continue
            standard_deviation = math.sqrt(variance)
            transformed = {
                asset_id: (value - mean_value) / standard_deviation for asset_id, value in available
            }
        elif node.operator is FactorOperator.WINSORIZE:
            if node.lower_quantile is None or node.upper_quantile is None:
                raise RuntimeError("compiled WINSORIZE node lost quantiles")
            raw_values = [value for _, value in available]
            lower = _type7_quantile(raw_values, node.lower_quantile)
            upper = _type7_quantile(raw_values, node.upper_quantile)
            transformed = {asset_id: min(upper, max(lower, value)) for asset_id, value in available}
        else:
            raise RuntimeError("non-panel operator passed to panel transform")
        for asset_id, value in transformed.items():
            values_by_asset[asset_id][index] = value
        for asset_id, series in source_by_asset.items():
            if series[index] is None:
                reasons_by_asset[asset_id][index] = PanelFactorUnavailableReason.NUMERIC_UNAVAILABLE
    return values_by_asset, reasons_by_asset


def _validate_panel(
    assets: tuple[FactorPanelAsset, ...],
    *,
    maximum_assets: int,
    maximum_bars_per_asset: int,
) -> int:
    if len(assets) < 2:
        raise ValueError("panel materialization requires at least two assets")
    if len(assets) > maximum_assets:
        raise ValueError(f"panel asset bound exceeded: {len(assets)}>{maximum_assets}")
    asset_ids = tuple(item.asset_id for item in assets)
    if len(asset_ids) != len(set(asset_ids)):
        raise ValueError("panel asset IDs must be unique")
    bar_count = len(assets[0].bars)
    if bar_count < 1 or bar_count > maximum_bars_per_asset:
        raise ValueError(f"panel bar bound exceeded: {bar_count}>{maximum_bars_per_asset}")
    reference = assets[0].bars
    seen_sessions: set[str] = set()
    previous: USBaselineBar | None = None
    for bar in reference:
        if previous is None or bar.session_id != previous.session_id:
            if bar.session_id in seen_sessions:
                raise ValueError("panel session IDs must not recur")
            seen_sessions.add(bar.session_id)
        elif bar.event_time - previous.event_time != timedelta(minutes=15):
            raise ValueError("panel requires continuous 15m clocks within each session")
        previous = bar
    for asset in assets:
        _validate_bars(asset.bars)
        if len(asset.bars) != bar_count:
            raise ValueError("panel assets must have equal bar counts")
        for expected, observed in zip(reference, asset.bars, strict=True):
            if observed.available_at != observed.event_time + timedelta(minutes=15):
                raise ValueError("panel requires 15m bar-close availability")
            if (
                observed.event_time != expected.event_time
                or observed.available_at != expected.available_at
                or observed.session_id != expected.session_id
            ):
                raise ValueError("panel assets must share aligned clocks and sessions")
    return bar_count


def _node_lookback(node: CompiledFactorNode, lookbacks: dict[str, int]) -> int:
    lookback = max((lookbacks[item] for item in node.inputs), default=1)
    if node.operator is FactorOperator.LAG:
        if node.lag_bars is None:
            raise RuntimeError("compiled LAG lost lag_bars")
        lookback += node.lag_bars
    elif node.window_bars is not None:
        lookback += node.window_bars - 1
    return lookback


def _mask_node(
    values: list[float | None],
    reasons: list[PanelFactorUnavailableReason | None],
    bars: tuple[USBaselineBar, ...],
    lookback: int,
) -> None:
    """Apply the complete-case contract BEFORE any downstream node consumes values.

    Warm-up is session-local, including when sessions are evaluated together.
    Endpoint-return/lag operators still require complete intervening bars, as in
    the frozen A1 root contract. This does not change the legacy evaluator.
    """
    session_start = 0
    for index, bar in enumerate(bars):
        if index == 0 or bar.session_id != bars[index - 1].session_id:
            session_start = index
        reason = reasons[index]
        value = values[index]
        if index - session_start + 1 < lookback:
            reason = PanelFactorUnavailableReason.INSUFFICIENT_HISTORY
        elif any(not item.is_complete for item in bars[index - lookback + 1 : index + 1]):
            reason = PanelFactorUnavailableReason.INCOMPLETE_BAR
        elif value is None or not math.isfinite(value):
            reason = reason or PanelFactorUnavailableReason.NUMERIC_UNAVAILABLE
        else:
            reason = None
        reasons[index] = reason
        if reason is not None:
            values[index] = None


def materialize_compiled_factor_panel(
    compiled: CompiledFactorBatch,
    assets: tuple[FactorPanelAsset, ...],
    *,
    minimum_cross_section: int = 2,
    regime_mask: FactorPanelRegimeMask | None = None,
    maximum_assets: int = 256,
    maximum_bars_per_asset: int = 64,
    maximum_node_value_cells: int = 2_000_000,
) -> FactorPanelMaterialization:
    if compiled.numeric_scope != "multi_asset_panel_v1":
        raise ValueError("panel materializer requires a panel-scoped compiled batch")
    if minimum_cross_section < 2 or minimum_cross_section > len(assets):
        raise ValueError("minimum_cross_section must be between two and asset count")
    bar_count = _validate_panel(
        assets,
        maximum_assets=maximum_assets,
        maximum_bars_per_asset=maximum_bars_per_asset,
    )
    estimated_node_value_cells = len(assets) * bar_count * len(compiled.nodes)
    if maximum_node_value_cells < 1 or estimated_node_value_cells > maximum_node_value_cells:
        raise ValueError(
            "panel node-value cell bound exceeded: "
            f"{estimated_node_value_cells}>{maximum_node_value_cells}; "
            "partition materialization by session"
        )
    if compiled.regime_policy_id is not None:
        if regime_mask is None:
            raise ValueError("compiled regime gates require an explicit regime mask")
        if regime_mask.policy_id != compiled.regime_policy_id:
            raise ValueError("regime mask policy does not match compiled graph policy")
    if regime_mask is not None and len(regime_mask.labels) != bar_count:
        raise ValueError("regime mask must align one label to every panel bar")
    if regime_mask is not None:
        if not regime_mask.source_evidence_id or not regime_mask.source_evidence_id.strip():
            raise ValueError("regime mask requires source evidence identity")
        if not regime_mask.label_available_at:
            raise ValueError("regime mask requires causal availability timestamps")
        if any(
            stamp > bar.available_at
            for stamp, bar in zip(regime_mask.label_available_at, assets[0].bars, strict=True)
        ):
            raise ValueError("regime label not available at formation time")

    series: dict[str, dict[str, list[float | None]]] = {asset.asset_id: {} for asset in assets}
    detailed_reasons: dict[tuple[str, str], list[PanelFactorUnavailableReason | None]] = {}
    evaluation_count = 0
    bars_by_asset = {asset.asset_id: asset.bars for asset in assets}
    lookbacks: dict[str, int] = {}
    for node in compiled.nodes:
        lookbacks[node.execution_id] = _node_lookback(node, lookbacks)
        if node.operator in _PANEL_OPERATORS:
            if len(node.inputs) != 1:
                raise RuntimeError("compiled panel operator is malformed")
            source_by_asset = {asset_id: series[asset_id][node.inputs[0]] for asset_id in series}
            transformed, panel_reasons_by_asset = _panel_transform(
                node,
                source_by_asset,
                bar_count=bar_count,
                minimum_cross_section=minimum_cross_section,
            )
            for asset_id, asset_series in series.items():
                asset_series[node.execution_id] = transformed[asset_id]
                detailed_reasons[(asset_id, node.execution_id)] = panel_reasons_by_asset[asset_id]
            evaluation_count += 1
        elif node.operator is FactorOperator.REGIME_GATE:
            if regime_mask is None or len(node.inputs) != 1:
                raise RuntimeError("compiled REGIME_GATE node is malformed")
            admitted = set(node.regime_labels)
            for asset_id, asset_series in series.items():
                source_series = asset_series[node.inputs[0]]
                output: list[float | None] = []
                regime_reasons: list[PanelFactorUnavailableReason | None] = []
                for value, label in zip(source_series, regime_mask.labels, strict=True):
                    output.append(value if label in admitted else None)
                    regime_reasons.append(
                        None if label in admitted else PanelFactorUnavailableReason.REGIME_EXCLUDED
                    )
                asset_series[node.execution_id] = output
                detailed_reasons[(asset_id, node.execution_id)] = regime_reasons
            evaluation_count += 1
        else:
            for asset_id, asset_series in series.items():
                dependencies = tuple(asset_series[item] for item in node.inputs)
                # The legacy LAG helper can return more than bar_count warm-up
                # cells when the partition is shorter than lag. Bound it here.
                asset_series[node.execution_id] = _evaluate_node_series(
                    node,
                    dependencies,
                    bars_by_asset[asset_id],
                )[:bar_count]
                evaluation_count += 1
        for asset_id, asset_series in series.items():
            reasons = detailed_reasons.setdefault((asset_id, node.execution_id), [None] * bar_count)
            _mask_node(
                asset_series[node.execution_id],
                reasons,
                bars_by_asset[asset_id],
                lookbacks[node.execution_id],
            )

    candidates: list[PanelFactorCandidateSeries] = []
    for asset in sorted(assets, key=lambda item: item.asset_id):
        for root in compiled.roots:
            if lookbacks[root.root_execution_id] != root.lookback_bars:
                raise RuntimeError("panel node/root lookback mismatch")
            candidates.append(
                PanelFactorCandidateSeries(
                    asset_id=asset.asset_id,
                    candidate_id=root.candidate_id,
                    values=tuple(series[asset.asset_id][root.root_execution_id]),
                    unavailable_reasons=tuple(
                        detailed_reasons[(asset.asset_id, root.root_execution_id)]
                    ),
                    lookback_bars=root.lookback_bars,
                )
            )
    return FactorPanelMaterialization(
        compiled_batch_id=compiled.batch_id,
        asset_count=len(assets),
        bar_count_per_asset=bar_count,
        minimum_cross_section=minimum_cross_section,
        node_series_evaluation_count=evaluation_count,
        candidates=tuple(candidates),
    )
