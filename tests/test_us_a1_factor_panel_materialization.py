from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from finagent.research.us_a1_factor_graph import (
    FactorDenominatorPolicy,
    FactorGraphSpec,
    FactorInputField,
    FactorNode,
    FactorOperator,
    FactorZeroDenominatorAction,
)
from finagent.research.us_a1_factor_materialization import compile_factor_graph_batch
from finagent.research.us_a1_factor_panel_materialization import (
    FactorPanelAsset,
    FactorPanelRegimeMask,
    PanelFactorUnavailableReason,
    materialize_compiled_factor_panel,
)
from finagent.research.us_baselines import USBaselineBar
from finagent.research.us_r3_alpha_catalog import (
    build_us_r3_executable_frontier_candidates,
)


def _panel(*, asset_count: int = 5, bar_count: int = 14) -> tuple[FactorPanelAsset, ...]:
    start = datetime(2026, 1, 5, 14, 30, tzinfo=UTC)
    assets: list[FactorPanelAsset] = []
    for asset_index in range(asset_count):
        bars: list[USBaselineBar] = []
        for bar_index in range(bar_count):
            event_time = start + timedelta(minutes=15 * bar_index)
            trend = (asset_index - 2) * 0.11 * bar_index
            curve = ((bar_index % 4) - 1.5) * (asset_index + 1) * 0.015
            close = 100.0 + asset_index * 3.0 + trend + curve
            open_value = close - 0.04 * (asset_index + 1)
            bars.append(
                USBaselineBar(
                    event_time=event_time,
                    available_at=event_time + timedelta(minutes=15),
                    session_id="2026-01-05",
                    open=open_value,
                    high=max(open_value, close) + 0.20 + asset_index * 0.01,
                    low=min(open_value, close) - 0.18 - asset_index * 0.01,
                    close=close,
                    volume=1_000.0 + asset_index * 170.0 + bar_index * (11.0 + asset_index),
                    is_complete=True,
                )
            )
        assets.append(FactorPanelAsset(asset_id=f"A{asset_index}", bars=tuple(bars)))
    return tuple(assets)


def test_frontier_graphs_materialize_on_aligned_ohlcv_panel_without_mt5() -> None:
    candidates = build_us_r3_executable_frontier_candidates()
    compiled = compile_factor_graph_batch(
        tuple(item.graph for item in candidates),
        admit_panel_operators=True,
    )
    panel = materialize_compiled_factor_panel(
        compiled,
        _panel(),
        minimum_cross_section=3,
    )

    assert compiled.numeric_scope == "multi_asset_panel_v1"
    assert panel.asset_count == 5
    assert panel.bar_count_per_asset == 14
    assert len(panel.candidates) == 15
    assert all(item.values[-1] is not None for item in panel.candidates)

    by_candidate: dict[str, list[float]] = {}
    for item in panel.candidates:
        value = item.values[-1]
        assert value is not None
        by_candidate.setdefault(item.candidate_id, []).append(value)
    for candidate in candidates:
        values = by_candidate[candidate.candidate_id]
        assert len(values) == 5
        if candidate.strategy.slug == "volume-conditioned-liquidity-reversal":
            assert min(values) == pytest.approx(0.0)
            assert max(values) == pytest.approx(1.0)
        else:
            assert sum(values) == pytest.approx(0.0, abs=1e-12)

    reordered = materialize_compiled_factor_panel(
        compiled,
        tuple(reversed(_panel())),
        minimum_cross_section=3,
    )
    assert {
        (item.asset_id, item.candidate_id): item.values for item in panel.candidates
    } == {
        (item.asset_id, item.candidate_id): item.values for item in reordered.candidates
    }


def test_panel_rank_uses_deterministic_average_percentiles_for_ties() -> None:
    graph = FactorGraphSpec(
        nodes=(
            FactorNode("close", FactorOperator.INPUT, input_field=FactorInputField.CLOSE),
            FactorNode("return", FactorOperator.SIMPLE_RETURN, ("close",), window_bars=2),
            FactorNode("rank", FactorOperator.CROSS_SECTION_RANK, ("return",)),
        ),
        output_node_id="rank",
    )
    assets = list(_panel(asset_count=4, bar_count=4))
    # Duplicate the complete price path so A0/A1 are tied exactly.
    assets[1] = FactorPanelAsset(asset_id="A1", bars=assets[0].bars)
    compiled = compile_factor_graph_batch((graph,), admit_panel_operators=True)
    result = materialize_compiled_factor_panel(compiled, tuple(assets))
    values = {item.asset_id: item.values[-1] for item in result.candidates}

    assert values["A0"] == values["A1"]
    assert values["A0"] == pytest.approx(1.0 / 6.0)
    assert values["A2"] == pytest.approx(2.0 / 3.0)
    assert values["A3"] == pytest.approx(1.0)


def test_panel_winsorization_uses_type7_quantiles() -> None:
    graph = FactorGraphSpec(
        nodes=(
            FactorNode("open", FactorOperator.INPUT, input_field=FactorInputField.OPEN),
            FactorNode("close", FactorOperator.INPUT, input_field=FactorInputField.CLOSE),
            FactorNode(
                "close_to_open",
                FactorOperator.SAFE_DIVIDE,
                ("close", "open"),
                denominator_policy=FactorDenominatorPolicy(
                    epsilon=1e-12,
                    action=FactorZeroDenominatorAction.UNAVAILABLE,
                ),
            ),
            FactorNode(
                "winsorized",
                FactorOperator.WINSORIZE,
                ("close_to_open",),
                lower_quantile=0.25,
                upper_quantile=0.75,
            ),
        ),
        output_node_id="winsorized",
    )
    assets: list[FactorPanelAsset] = []
    for index, close in enumerate((100.0, 101.0, 102.0, 200.0)):
        bar = _panel(asset_count=4, bar_count=1)[index].bars[0]
        assets.append(
            FactorPanelAsset(
                asset_id=f"A{index}",
                bars=(
                    USBaselineBar(
                        event_time=bar.event_time,
                        available_at=bar.available_at,
                        session_id=bar.session_id,
                        open=100.0,
                        high=close,
                        low=100.0,
                        close=close,
                        volume=bar.volume,
                        is_complete=True,
                    ),
                ),
            )
        )
    compiled = compile_factor_graph_batch((graph,), admit_panel_operators=True)
    result = materialize_compiled_factor_panel(compiled, tuple(assets))
    values = {item.asset_id: item.values[0] for item in result.candidates}

    assert values == {
        "A0": pytest.approx(1.0075),
        "A1": pytest.approx(1.01),
        "A2": pytest.approx(1.02),
        "A3": pytest.approx(1.265),
    }


def test_panel_zscore_reports_zero_cross_section_dispersion() -> None:
    graph = FactorGraphSpec(
        nodes=(
            FactorNode("close", FactorOperator.INPUT, input_field=FactorInputField.CLOSE),
            FactorNode("zscore", FactorOperator.CROSS_SECTION_ZSCORE, ("close",)),
        ),
        output_node_id="zscore",
    )
    assets = list(_panel(asset_count=3, bar_count=2))
    assets[1] = FactorPanelAsset("A1", assets[0].bars)
    assets[2] = FactorPanelAsset("A2", assets[0].bars)
    compiled = compile_factor_graph_batch((graph,), admit_panel_operators=True)
    result = materialize_compiled_factor_panel(compiled, tuple(assets))

    for item in result.candidates:
        assert item.values == (None, None)
        assert item.unavailable_reasons == (
            PanelFactorUnavailableReason.ZERO_CROSS_SECTION_DISPERSION,
            PanelFactorUnavailableReason.ZERO_CROSS_SECTION_DISPERSION,
        )


def test_regime_gate_requires_exact_policy_and_masks_excluded_bars() -> None:
    graph = FactorGraphSpec(
        nodes=(
            FactorNode("close", FactorOperator.INPUT, input_field=FactorInputField.CLOSE),
            FactorNode("return", FactorOperator.SIMPLE_RETURN, ("close",), window_bars=2),
            FactorNode("zscore", FactorOperator.CROSS_SECTION_ZSCORE, ("return",)),
            FactorNode(
                "gate",
                FactorOperator.REGIME_GATE,
                ("zscore",),
                regime_labels=("HIGH_VOL",),
            ),
        ),
        output_node_id="gate",
        regime_policy_id="reviewed-regime-policy",
    )
    compiled = compile_factor_graph_batch((graph,), admit_panel_operators=True)
    assets = _panel(asset_count=4, bar_count=6)

    with pytest.raises(ValueError, match="explicit regime mask"):
        materialize_compiled_factor_panel(compiled, assets)
    with pytest.raises(ValueError, match="does not match"):
        materialize_compiled_factor_panel(
            compiled,
            assets,
            regime_mask=FactorPanelRegimeMask("wrong-policy", ("HIGH_VOL",) * 6),
        )

    result = materialize_compiled_factor_panel(
        compiled,
        assets,
        regime_mask=FactorPanelRegimeMask(
            "reviewed-regime-policy",
            ("LOW_VOL", "LOW_VOL", "LOW_VOL", "HIGH_VOL", "HIGH_VOL", "HIGH_VOL"),
        ),
    )
    for item in result.candidates:
        assert item.values[2] is None
        assert item.unavailable_reasons[2] is PanelFactorUnavailableReason.REGIME_EXCLUDED
        assert item.values[-1] is not None


def test_panel_materializer_fails_closed_on_clock_and_resource_mismatch() -> None:
    candidate = build_us_r3_executable_frontier_candidates()[0]
    compiled = compile_factor_graph_batch((candidate.graph,), admit_panel_operators=True)
    assets = _panel(asset_count=3, bar_count=5)
    shortened = FactorPanelAsset("A2", assets[2].bars[:-1])
    with pytest.raises(ValueError, match="equal bar counts"):
        materialize_compiled_factor_panel(compiled, (*assets[:2], shortened))
    with pytest.raises(ValueError, match="asset bound exceeded"):
        materialize_compiled_factor_panel(compiled, assets, maximum_assets=2)
    with pytest.raises(ValueError, match="bar bound exceeded"):
        materialize_compiled_factor_panel(compiled, assets, maximum_bars_per_asset=4)
    with pytest.raises(ValueError, match="node-value cell bound exceeded"):
        materialize_compiled_factor_panel(compiled, assets, maximum_node_value_cells=1)
