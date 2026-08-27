from __future__ import annotations

from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


root = Path(__file__).resolve().parents[1]

# CLI configuration surface.
path = root / "scripts/run_local_ashare_factor_research.py"
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    "from finagent.research.ashare_factor_acceptance import (\n"
    "    AshareFactorResearchAcceptanceEngine,\n"
    ")\n",
    "from finagent.research.ashare_factor_acceptance import (\n"
    "    AshareFactorResearchAcceptanceEngine,\n"
    "    AshareResearchVerdictPolicy,\n"
    ")\n",
    "CLI verdict import",
)
text = replace_once(
    text,
    "from finagent.research.factor_quant_discovery import AgentFactorQuantDiscoveryLoop\n",
    "from finagent.research.factor_quant_discovery import AgentFactorQuantDiscoveryLoop\n"
    "from finagent.research.factor_stability import FactorStabilityConfig\n",
    "CLI stability import",
)
text = replace_once(
    text,
    "    engine = AshareFactorResearchAcceptanceEngine(\n"
    "        development_analyzer=development_analyzer,\n"
    "        validation_analyzer=validation_analyzer,\n"
    "        selector=selector,\n"
    "    )\n",
    "    engine = AshareFactorResearchAcceptanceEngine(\n"
    "        development_analyzer=development_analyzer,\n"
    "        validation_analyzer=validation_analyzer,\n"
    "        selector=selector,\n"
    "        stability_config=FactorStabilityConfig(\n"
    "            rolling_window=int(values.get(\"stability_rolling_window\", 63)),\n"
    "            rolling_step=int(values.get(\"stability_rolling_step\", 21)),\n"
    "            min_rolling_periods=int(\n"
    "                values.get(\"stability_min_rolling_periods\", 20)\n"
    "            ),\n"
    "            hac_lags=int(values.get(\"stability_hac_lags\", 5)),\n"
    "            bootstrap_samples=int(\n"
    "                values.get(\"stability_bootstrap_samples\", 500)\n"
    "            ),\n"
    "            bootstrap_block_length=int(\n"
    "                values.get(\"stability_bootstrap_block_length\", 20)\n"
    "            ),\n"
    "            bootstrap_seed=int(\n"
    "                values.get(\"stability_bootstrap_seed\", 20_260_827)\n"
    "            ),\n"
    "        ),\n"
    "        verdict_policy=AshareResearchVerdictPolicy(\n"
    "            min_validation_rank_icir=float(\n"
    "                values.get(\"verdict_min_validation_rank_icir\", 0.0)\n"
    "            ),\n"
    "            min_validation_long_short_sharpe=float(\n"
    "                values.get(\"verdict_min_validation_long_short_sharpe\", 0.0)\n"
    "            ),\n"
    "            max_hac_pvalue=float(values.get(\"verdict_max_hac_pvalue\", 0.05)),\n"
    "            max_bootstrap_pvalue=float(\n"
    "                values.get(\"verdict_max_bootstrap_pvalue\", 0.05)\n"
    "            ),\n"
    "        ),\n"
    "    )\n",
    "CLI stability and verdict configuration",
)
path.write_text(text, encoding="utf-8")

# Example configuration.
path = root / "configs/research/local_ashare_factor_research.example.toml"
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    "policy_min_liquidity_observations = 10\n",
    "policy_min_liquidity_observations = 10\n"
    "# Hidden pre-split history initializes rolling liquidity without exposing it as evidence.\n"
    "policy_liquidity_warmup_calendar_days = 120\n",
    "example warmup config",
)
text = replace_once(
    text,
    "smoke_lookback = 64\n\n# Used only when mode = \"agent\".\n",
    "smoke_lookback = 64\n\n"
    "# A2.5 stability and dependence-aware inference. These values are part of the report identity.\n"
    "stability_rolling_window = 63\n"
    "stability_rolling_step = 21\n"
    "stability_min_rolling_periods = 20\n"
    "stability_hac_lags = 5\n"
    "stability_bootstrap_samples = 500\n"
    "stability_bootstrap_block_length = 20\n"
    "stability_bootstrap_seed = 20260827\n\n"
    "# Research verdict. System completion remains separate and A2 is never promotion-eligible.\n"
    "verdict_min_validation_rank_icir = 0.0\n"
    "verdict_min_validation_long_short_sharpe = 0.0\n"
    "verdict_max_hac_pvalue = 0.05\n"
    "verdict_max_bootstrap_pvalue = 0.05\n\n"
    "# Used only when mode = \"agent\".\n",
    "example stability config",
)
path.write_text(text, encoding="utf-8")

# Public research API.
path = root / "src/finagent/research/__init__.py"
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    "from .factor_quant_discovery import (\n"
    "    AgentFactorQuantDiscoveryLoop,\n"
    "    AgentFactorQuantDiscoveryResult,\n"
    "    AgentFactorQuantDiscoveryRound,\n"
    ")\n",
    "from .factor_quant_discovery import (\n"
    "    AgentFactorQuantDiscoveryLoop,\n"
    "    AgentFactorQuantDiscoveryResult,\n"
    "    AgentFactorQuantDiscoveryRound,\n"
    ")\n"
    "from .factor_stability import (\n"
    "    FactorCandidateStabilityReport,\n"
    "    FactorFamilyStabilityReport,\n"
    "    FactorMultiplicityDiagnostics,\n"
    "    FactorRollingICPoint,\n"
    "    FactorStabilityAnalyzer,\n"
    "    FactorStabilityConfig,\n"
    "    FactorSubperiodStability,\n"
    "    adjust_family_pvalues,\n"
    ")\n",
    "research stability imports",
)
text = replace_once(
    text,
    "    \"FactorCandidateDiagnostics\",\n",
    "    \"FactorCandidateDiagnostics\",\n"
    "    \"FactorCandidateStabilityReport\",\n",
    "research stability candidate export",
)
text = replace_once(
    text,
    "    \"FactorFamilyDiagnostics\",\n",
    "    \"FactorFamilyDiagnostics\",\n"
    "    \"FactorFamilyStabilityReport\",\n",
    "research stability family export",
)
text = replace_once(
    text,
    "    \"FactorModelStatisticalValidation\",\n",
    "    \"FactorModelStatisticalValidation\",\n"
    "    \"FactorMultiplicityDiagnostics\",\n",
    "research multiplicity export",
)
text = replace_once(
    text,
    "    \"FactorQuantFamilyReport\",\n",
    "    \"FactorQuantFamilyReport\",\n"
    "    \"FactorRollingICPoint\",\n"
    "    \"FactorStabilityAnalyzer\",\n"
    "    \"FactorStabilityConfig\",\n"
    "    \"FactorSubperiodStability\",\n",
    "research stability exports",
)
text = replace_once(
    text,
    "    \"adjust_pvalues\",\n",
    "    \"adjust_family_pvalues\",\n"
    "    \"adjust_pvalues\",\n",
    "research pvalue export",
)
path.write_text(text, encoding="utf-8")

# Regression assertions for the existing real adapter integration.
path = root / "tests/test_ashare_factor_acceptance_a2.py"
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    "    assert result.candidates[0].primary.periods >= 10\n"
    "    assert report.splits[\"development\"].average_eligible_assets >= 5\n",
    "    assert result.candidates[0].primary.periods >= 10\n"
    "    summary = report.splits[\"development\"]\n"
    "    assert summary.warmup_timestamps >= 3\n"
    "    assert summary.first_session_eligible_assets >= 5\n"
    "    assert summary.minimum_eligible_assets >= 5\n"
    "    assert summary.average_eligible_assets >= 5\n",
    "warmup regression assertions",
)
text = replace_once(
    text,
    "policy_min_liquidity_observations = 3\n",
    "policy_min_liquidity_observations = 3\n"
    "policy_liquidity_warmup_calendar_days = 30\n"
    "stability_rolling_window = 20\n"
    "stability_rolling_step = 10\n"
    "stability_min_rolling_periods = 10\n"
    "stability_hac_lags = 3\n"
    "stability_bootstrap_samples = 100\n"
    "stability_bootstrap_block_length = 5\n"
    "stability_bootstrap_seed = 7\n",
    "CLI test stability config",
)
text = replace_once(
    text,
    "    assert payload[\"passed\"] is True\n"
    "    assert payload[\"mode\"] == \"deterministic\"\n",
    "    assert payload[\"passed\"] is True\n"
    "    assert payload[\"system_acceptance\"][\"passed\"] is True\n"
    "    assert payload[\"research_outcome\"][\"promotion_eligible\"] is False\n"
    "    assert payload[\"mode\"] == \"deterministic\"\n",
    "CLI verdict assertions",
)
text = replace_once(
    text,
    "    assert payload[\"validation_ensemble\"][\"primary_label\"] == \"forward_simple_return_1\"\n"
    "    assert \"transaction_cost\" not in payload[\"validation_comparison\"]\n",
    "    assert payload[\"validation_ensemble\"][\"primary_label\"] == \"forward_simple_return_1\"\n"
    "    assert payload[\"universe_policy\"][\"splits\"][\"development\"][\"first_session_eligible_assets\"] >= 5\n"
    "    assert len(payload[\"development_stability\"][\"candidates\"]) == 3\n"
    "    assert len(payload[\"validation_stability\"][\"multiplicity\"]) == 3\n"
    "    assert payload[\"validation_comparison\"][\"comparison_semantics\"] == (\n"
    "        \"development-frozen direction; signed deltas\"\n"
    "    )\n"
    "    assert \"transaction_cost\" not in payload[\"validation_comparison\"]\n",
    "CLI stability assertions",
)
text = replace_once(
    text,
    "    assert replay_payload[\"validation_report\"][\"report_id\"] == payload[\"validation_report\"][\"report_id\"]\n",
    "    assert replay_payload[\"validation_report\"][\"report_id\"] == payload[\"validation_report\"][\"report_id\"]\n"
    "    assert replay_payload[\"development_stability\"][\"report_id\"] == payload[\"development_stability\"][\"report_id\"]\n"
    "    assert replay_payload[\"validation_stability\"][\"report_id\"] == payload[\"validation_stability\"][\"report_id\"]\n"
    "    assert replay_payload[\"research_outcome\"] == payload[\"research_outcome\"]\n",
    "CLI replay stability assertions",
)
path.write_text(text, encoding="utf-8")

# Canonical test guide.
path = root / "docs/testing/testing.md"
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    "→ per-session PIT universe policy\n"
    "→ panel-native generated-feature materialization\n",
    "→ per-session PIT universe policy with hidden pre-split liquidity warm-up\n"
    "→ panel-native generated-feature materialization\n",
    "testing warmup flow",
)
text = replace_once(
    text,
    "- Factor Quant reports contain finite IC/ICIR, quantile and turnover diagnostics;\n"
    "- no execution-cost or broker claim appears in the report;\n"
    "- report exits with `passed = true` even when factors have weak or negative performance.\n",
    "- split summaries report non-empty warm-up history and a non-artificial first-session eligibility count;\n"
    "- Factor Quant reports contain finite IC/ICIR, quantile and turnover diagnostics;\n"
    "- stability reports contain rolling/yearly RankIC, HAC, deterministic block bootstrap, monotonicity, turnover/coverage stability and Holm/BH adjustments;\n"
    "- `passed = true` and `system_acceptance.passed = true` mean workflow completion only; inspect `research_outcome` for factor validity;\n"
    "- signed validation deltas use the direction frozen in development; absolute-magnitude deltas are separately named;\n"
    "- no execution-cost or broker claim appears in the report, and `promotion_eligible` remains false.\n",
    "testing A2.5 acceptance checks",
)
text = replace_once(
    text,
    "The `acceptance_id`, candidate denominator, development report, frozen ensemble and validation report must match exactly. Replay must not call the LLM.\n",
    "The `acceptance_id`, candidate denominator, development/validation Factor Quant and stability reports, frozen ensemble and research verdict must match exactly. Replay must not call the LLM. Reports produced before schema v2 must be regenerated before using `--assert-replay`.\n",
    "testing replay semantics",
)
text = replace_once(
    text,
    "  tests/test_ashare_factor_acceptance_a2.py \\\n  tests/test_agent_generation_robustness_observability.py\n",
    "  tests/test_ashare_factor_acceptance_a2.py \\\n  tests/test_ashare_research_correctness_a25.py \\\n  tests/test_agent_generation_robustness_observability.py\n",
    "testing POSIX test list",
)
text = replace_once(
    text,
    "  tests\\test_ashare_factor_acceptance_a2.py `\n"
    "  tests\\test_agent_generation_robustness_observability.py\n",
    "  tests\\test_ashare_factor_acceptance_a2.py `\n"
    "  tests\\test_ashare_research_correctness_a25.py `\n"
    "  tests\\test_agent_generation_robustness_observability.py\n",
    "testing Windows test list",
)
path.write_text(text, encoding="utf-8")
