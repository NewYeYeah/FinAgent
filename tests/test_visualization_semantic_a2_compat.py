from __future__ import annotations

from finagent.visualization.semantic import EvidenceStage, parse_evidence_report

from tests.test_research_visualization import _report


def test_a2p5_acceptance_projects_without_changing_legacy_semantics() -> None:
    payload = _report()
    bundle = parse_evidence_report(payload, source_uri="reports/a2p5.json")
    assert bundle.root.stage is EvidenceStage.A2_FACTOR_ACCEPTANCE
    assert bundle.root.evidence_id == payload["acceptance_id"]
    assert bundle.system_status == "PASS"
    assert bundle.research_status == "ENSEMBLE_VALIDATION_FAILED"
    assert bundle.reserve_status == "untouched"
    assert bundle.promotion_eligible is False
    assert len(bundle.factors) == len(payload["candidate_denominator"])
    selected = [factor for factor in bundle.factors if factor.selected]
    assert len(selected) == 1
    assert selected[0].feature_id == "factor-a"
    assert selected[0].metrics["development_rank_icir"] == 0.15
    assert selected[0].metrics["validation_rank_icir"] == -0.02
    lineage = bundle.lineage()
    assert bundle.root.evidence_id in {node.evidence_id for node in lineage.nodes}
