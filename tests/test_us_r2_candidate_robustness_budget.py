from __future__ import annotations

from finagent.domain.market_bars import BarInterval
from finagent.research.us_a1_factor_validation import validate_factor_graph
from finagent.research.us_a1_legacy_graphs import legacy_a0_factor_graph_with_window
from finagent.research.us_agent_value_protocol import canonical_us_a0_primitive_vocabulary
from finagent.research.us_r1_materialization import effective_us_r1_window_bars


def test_every_frozen_a0_candidate_scaled_to_5m_remains_a1_admissible() -> None:
    maximum_effective_window = 0
    for candidate in canonical_us_a0_primitive_vocabulary().all_candidates():
        effective_window = effective_us_r1_window_bars(candidate, BarInterval.MINUTE_5)
        maximum_effective_window = max(maximum_effective_window, effective_window)
        graph = legacy_a0_factor_graph_with_window(candidate, window_bars=effective_window)
        evidence = validate_factor_graph(graph)
        assert evidence.valid, (candidate.structural_key, evidence.blockers)
        assert evidence.canonicalization is not None
        assert evidence.canonicalization.lookback_bars == effective_window
        assert graph.budget.max_window_bars >= effective_window
        assert graph.budget.max_lookback_bars >= effective_window

    assert maximum_effective_window == 37
