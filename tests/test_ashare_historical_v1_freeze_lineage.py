from pathlib import Path

from finagent.runtime import ashare_historical_v1_freeze as legacy
from finagent.runtime.ashare_historical_v1_freeze_lineage import (
    AC5_EVIDENCE_CORE_PATHS,
    AC5_POST_AC3_NON_ECONOMIC_PATHS,
    _evidence_core_drift,
)

ROOT = Path(__file__).resolve().parents[1]

# A-C3 implementation merge, before the launcher wording compatibility patch and
# the explicit no-alpha acceptance verifier were added.
AC3_EVIDENCE_SHA = "85e0acf5114139d53b4de87879672c6aade09944"
# Merge that contains both reviewed post-A-C3 changes.
NO_ALPHA_VERIFIER_SHA = "007be18368c5c3a581475561245ed0f093c5bea9"


def test_known_post_ac3_verifier_changes_do_not_invalidate_economic_evidence() -> None:
    legacy_drift = set(
        legacy._historical_core_drift(
            ROOT,
            evidence_sha=AC3_EVIDENCE_SHA,
            release_sha=NO_ALPHA_VERIFIER_SHA,
        )
    )
    assert legacy_drift == {
        "scripts/run_workbench_control.py",
        "src/finagent/runtime/ashare_historical_acceptance_terminal.py",
    }

    assert _evidence_core_drift(
        ROOT,
        evidence_sha=AC3_EVIDENCE_SHA,
        release_sha=NO_ALPHA_VERIFIER_SHA,
    ) == ()


def test_post_ac3_exclusions_are_narrow_and_explicit() -> None:
    assert AC5_POST_AC3_NON_ECONOMIC_PATHS == {
        "scripts/run_workbench_control.py",
        "src/finagent/runtime/ashare_historical_acceptance_terminal.py",
    }
    assert not AC5_POST_AC3_NON_ECONOMIC_PATHS.intersection(AC5_EVIDENCE_CORE_PATHS)
    # The actual A2.6/A4/data/model/execution implementation remains protected.
    for protected in (
        "src/finagent/application",
        "src/finagent/backtest",
        "src/finagent/data",
        "src/finagent/domain",
        "src/finagent/models",
        "src/finagent/research",
        "src/finagent/services",
    ):
        assert protected in AC5_EVIDENCE_CORE_PATHS
