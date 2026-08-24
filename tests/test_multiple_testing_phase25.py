from __future__ import annotations

import numpy as np

from finagent.domain.experiment_family import CorrectionMethod
from finagent.research.validation import adjust_pvalues


def test_holm_and_bh_adjustments_are_monotone_and_bounded() -> None:
    pvalues = (0.001, 0.01, 0.04, 0.3)
    holm = adjust_pvalues(pvalues, method=CorrectionMethod.HOLM, alpha=0.05)
    bh = adjust_pvalues(pvalues, method=CorrectionMethod.BENJAMINI_HOCHBERG, alpha=0.05)
    assert holm.rejected == (True, True, False, False)
    assert all(0.0 <= value <= 1.0 for value in holm.adjusted_pvalues)
    assert all(0.0 <= value <= 1.0 for value in bh.adjusted_pvalues)
    assert np.all(np.asarray(bh.adjusted_pvalues) <= np.asarray(holm.adjusted_pvalues) + 1e-12)


def test_bonferroni_uses_whole_family_size() -> None:
    result = adjust_pvalues((0.01, 0.02, 0.2), method="bonferroni")
    assert result.adjusted_pvalues == (0.03, 0.06, 0.6000000000000001)
    assert result.rejected == (True, False, False)
