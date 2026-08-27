from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"expected patch anchor is absent: {path}: {old[:80]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def patch_core() -> None:
    path = "src/finagent/research/ashare_robust_program.py"
    replace_once(
        path,
        "from .factor_quant import (\n",
        "from .ashare_universe import (\n"
        "    AshareCandidateUniverseSelection,\n"
        "    AshareResearchUniverseReport,\n"
        ")\n"
        "from .factor_quant import (\n",
    )
    replace_once(
        path,
        '''    def __post_init__(self) -> None:\n        bounded = (\n            self.min_positive_fold_ratio,\n            self.min_direction_consistency,\n            self.min_coverage,\n            self.min_quantile_monotonicity,\n            self.min_horizon_sign_consistency,\n            self.max_hac_pvalue,\n            self.max_bh_qvalue,\n        )\n        if any(not math.isfinite(value) or not 0.0 <= value <= 1.0 for value in bounded):\n            raise ValueError("bounded robust gate values must be in [0, 1]")\n        if self.max_mean_one_way_turnover < 0 or self.turnover_penalty < 0:\n            raise ValueError("turnover gate values must be non-negative")\n''',
        '''    def __post_init__(self) -> None:\n        bounded = (\n            self.min_positive_fold_ratio,\n            self.min_direction_consistency,\n            self.min_coverage,\n            self.min_quantile_monotonicity,\n            self.min_horizon_sign_consistency,\n            self.max_hac_pvalue,\n            self.max_bh_qvalue,\n        )\n        if any(\n            not math.isfinite(value) or not 0.0 <= value <= 1.0\n            for value in bounded\n        ):\n            raise ValueError("bounded robust gate values must be in [0, 1]")\n        unbounded = (\n            self.min_pooled_rank_icir,\n            self.min_mean_fold_rank_icir,\n            self.min_worst_fold_rank_icir,\n            self.min_mean_fold_long_short_sharpe,\n            self.max_mean_one_way_turnover,\n            self.turnover_penalty,\n        )\n        if any(not math.isfinite(value) for value in unbounded):\n            raise ValueError("robust gate values must be finite")\n        if self.max_mean_one_way_turnover < 0 or self.turnover_penalty < 0:\n            raise ValueError("turnover gate values must be non-negative")\n''',
    )
    replace_once(
        path,
        '''class AshareRobustResearchProgramResult:\n    mode: str\n    program_spec: AshareResearchProgramSpec\n    candidates: tuple[GeneratedFeatureArtifact, ...]\n''',
        '''class AshareRobustResearchProgramResult:\n    mode: str\n    program_spec: AshareResearchProgramSpec\n    candidate_universe: AshareCandidateUniverseSelection\n    universe_policy: AshareResearchUniverseReport\n    candidates: tuple[GeneratedFeatureArtifact, ...]\n''',
    )
    replace_once(
        path,
        '''        if digests != {\n            candidate.feature_digest for candidate in self.gate_report.candidates\n        }:\n            raise ValueError("gate denominator differs from candidates")\n        if not {\n            component.feature_digest for component in self.frozen_selection.components\n        }.issubset(digests):\n            raise ValueError("robust selection references candidate outside denominator")\n''',
        '''        if digests != {\n            candidate.feature_digest for candidate in self.gate_report.candidates\n        }:\n            raise ValueError("gate denominator differs from candidates")\n        if self.walk_forward_report.program_spec_id != self.program_spec.spec_id:\n            raise ValueError("walk-forward report differs from program spec")\n        if self.walk_forward_report.plan_id != self.program_spec.plan.plan_id:\n            raise ValueError("walk-forward report differs from frozen plan")\n        if self.gate_report.walk_forward_report_id != self.walk_forward_report.report_id:\n            raise ValueError("gate report does not belong to walk-forward report")\n        if self.frozen_selection.walk_forward_report_id != self.walk_forward_report.report_id:\n            raise ValueError("robust selection does not belong to walk-forward report")\n        if self.frozen_selection.gate_report_id != self.gate_report.gate_report_id:\n            raise ValueError("robust selection does not belong to gate report")\n        if self.candidate_universe.selection_id != self.program_spec.candidate_selection_id:\n            raise ValueError("candidate universe differs from program spec")\n        if self.universe_policy.data_version != self.program_spec.universe_policy_version:\n            raise ValueError("universe policy differs from program spec")\n        if not {\n            component.feature_digest for component in self.frozen_selection.components\n        }.issubset(digests):\n            raise ValueError("robust selection references candidate outside denominator")\n''',
    )
    replace_once(
        path,
        '''            "program_spec": self.program_spec.to_dict(),\n            "program_status": self.program_status,\n            "data_version": self.program_spec.data_version,\n            "candidate_denominator": [\n''',
        '''            "program_spec": self.program_spec.to_dict(),\n            "program_status": self.program_status,\n            "data_version": self.program_spec.data_version,\n            "candidate_universe": self.candidate_universe.to_dict(),\n            "universe_policy": self.universe_policy.to_dict(),\n            "candidate_denominator": [\n''',
    )


def patch_feedback_and_cli() -> None:
    replace_once(
        "src/finagent/research/factor_feedback_v3.py",
        '                "2018-2024 internal development/walk-forward evidence only; "\n',
        '                "internal development/walk-forward evidence only; "\n',
    )
    replace_once(
        "scripts/run_local_ashare_robust_research.py",
        '''    result = AshareRobustResearchProgramResult(\n        mode=mode,\n        program_spec=spec,\n        candidates=tuple(candidates),\n''',
        '''    result = AshareRobustResearchProgramResult(\n        mode=mode,\n        program_spec=spec,\n        candidate_universe=candidate_selection,\n        universe_policy=universe_report,\n        candidates=tuple(candidates),\n''',
    )


def patch_exports() -> None:
    path = "src/finagent/research/__init__.py"
    replace_once(
        path,
        "from .agent_family import (\n",
        '''from .ashare_robust_program import (\n    AshareExpandingWalkForwardPlan,\n    AshareProgramReservationPlan,\n    AshareResearchProgramSpec,\n    AshareRobustCandidateGate,\n    AshareRobustCandidateGateConfig,\n    AshareRobustCandidateGateEvaluation,\n    AshareRobustCandidateGateReport,\n    AshareRobustFactorComponent,\n    AshareRobustFactorSelection,\n    AshareRobustFactorSelector,\n    AshareRobustResearchProgramResult,\n    AshareRobustSelectorConfig,\n    AshareWalkForwardCandidateReport,\n    AshareWalkForwardFactorAnalyzer,\n    AshareWalkForwardFamilyReport,\n    AshareWalkForwardFold,\n    AshareWalkForwardFoldCandidate,\n    SQLiteAshareResearchProgramSpecStore,\n)\nfrom .agent_family import (\n''',
    )
    replace_once(
        path,
        "from .factor_feedback_v2 import (\n",
        '''from .factor_feedback_v3 import (\n    AgentAshareRobustDiscoveryLoop,\n    AgentAshareRobustDiscoveryResult,\n    AgentAshareRobustDiscoveryRound,\n    AshareRobustAgentFeedbackV3,\n    AshareRobustFeedbackAwareMarketFeatureCandidateGenerator,\n    AshareRobustFeedbackCandidate,\n    AshareRobustFeedbackFold,\n)\nfrom .factor_feedback_v2 import (\n''',
    )
    replace_once(
        path,
        '    "AgentCandidateStatisticalValidation",\n',
        '''    "AgentAshareRobustDiscoveryLoop",\n    "AgentAshareRobustDiscoveryResult",\n    "AgentAshareRobustDiscoveryRound",\n    "AgentCandidateStatisticalValidation",\n''',
    )
    replace_once(
        path,
        '    "AgentMarketValidationReport",\n',
        '''    "AgentMarketValidationReport",\n    "AshareExpandingWalkForwardPlan",\n    "AshareProgramReservationPlan",\n    "AshareResearchProgramSpec",\n    "AshareRobustAgentFeedbackV3",\n    "AshareRobustCandidateGate",\n    "AshareRobustCandidateGateConfig",\n    "AshareRobustCandidateGateEvaluation",\n    "AshareRobustCandidateGateReport",\n    "AshareRobustFactorComponent",\n    "AshareRobustFactorSelection",\n    "AshareRobustFactorSelector",\n    "AshareRobustFeedbackAwareMarketFeatureCandidateGenerator",\n    "AshareRobustFeedbackCandidate",\n    "AshareRobustFeedbackFold",\n    "AshareRobustResearchProgramResult",\n    "AshareRobustSelectorConfig",\n    "AshareWalkForwardCandidateReport",\n    "AshareWalkForwardFactorAnalyzer",\n    "AshareWalkForwardFamilyReport",\n    "AshareWalkForwardFold",\n    "AshareWalkForwardFoldCandidate",\n''',
    )
    replace_once(
        path,
        '    "SQLiteAgentFamilyValidationStore",\n',
        '''    "SQLiteAgentFamilyValidationStore",\n    "SQLiteAshareResearchProgramSpecStore",\n''',
    )


def patch_main_ci() -> None:
    path = ".github/workflows/tests.yml"
    replace_once(
        path,
        '''            src/finagent/research/ashare_factor_acceptance.py \\\n            src/finagent/research/resilient_candidate_generator.py \\\n''',
        '''            src/finagent/research/ashare_factor_acceptance.py \\\n            src/finagent/research/ashare_robust_program.py \\\n            src/finagent/research/factor_feedback_v3.py \\\n            src/finagent/research/resilient_candidate_generator.py \\\n''',
    )
    replace_once(
        path,
        '''            tests/test_ashare_factor_acceptance_a2.py \\\n            scripts/certify_local_ashare_data.py \\\n''',
        '''            tests/test_ashare_factor_acceptance_a2.py \\\n            tests/test_ashare_robust_research_a26.py \\\n            scripts/certify_local_ashare_data.py \\\n''',
    )
    replace_once(
        path,
        '''            scripts/run_local_ashare_factor_research.py \\\n            --select E4,E7,E9,F\n''',
        '''            scripts/run_local_ashare_factor_research.py \\\n            scripts/run_local_ashare_robust_research.py \\\n            --select E4,E7,E9,F\n''',
    )
    replace_once(
        path,
        '''            src/finagent/research/factor_quant_discovery.py \\\n            src/finagent/research/resilient_candidate_generator.py \\\n''',
        '''            src/finagent/research/factor_quant_discovery.py \\\n            src/finagent/research/factor_feedback_v3.py \\\n            src/finagent/research/resilient_candidate_generator.py \\\n''',
    )
    replace_once(
        path,
        '''            src/finagent/data/ashare_supplemental.py \\\n            src/finagent/backtest/market_study.py\n''',
        '''            src/finagent/data/ashare_supplemental.py \\\n            src/finagent/research/ashare_robust_program.py \\\n            src/finagent/research/factor_feedback_v3.py \\\n            src/finagent/backtest/market_study.py\n''',
    )


if __name__ == "__main__":
    patch_core()
    patch_feedback_and_cli()
    patch_exports()
    patch_main_ci()
