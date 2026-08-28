from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"missing A4 CI patch anchor: {path}: {old[:80]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    alpha = "src/finagent/models/alpha/ashare_frozen.py"
    replace_once(
        alpha,
        "from finagent.domain.experiments import ArtifactRef\n",
        "from finagent.domain.assets import AssetId\nfrom finagent.domain.experiments import ArtifactRef\n",
    )
    replace_once(
        alpha,
        "from finagent.domain.research import DatasetRequest, FeatureWindow\n",
        "from finagent.domain.research import (\n    DatasetRequest,\n    FeatureWindow,\n    ResearchSplit,\n)\n",
    )
    replace_once(
        alpha,
        "    ) -> tuple[np.ndarray, np.ndarray, object]:\n",
        "    ) -> tuple[np.ndarray, np.ndarray, ResearchSplit]:\n",
    )
    replace_once(
        alpha,
        '''                winsorized = winsorize_cross_section(\n                    values,\n                    lower_quantile=self.winsor_lower_quantile,\n                    upper_quantile=self.winsor_upper_quantile,\n                    eligible=row_mask,\n                )\n                standardized = cross_sectional_zscore(winsorized, eligible=row_mask)\n''',
        '''                winsorized = winsorize_cross_section(\n                    values.tolist(),\n                    lower_quantile=self.winsor_lower_quantile,\n                    upper_quantile=self.winsor_upper_quantile,\n                    eligible=row_mask.tolist(),\n                )\n                standardized = cross_sectional_zscore(\n                    winsorized.tolist(),\n                    eligible=row_mask.tolist(),\n                )\n''',
    )
    replace_once(
        alpha,
        "        eligible: Mapping[object, bool] | None = None,\n",
        "        eligible: Mapping[AssetId, bool] | None = None,\n",
    )
    replace_once(
        alpha,
        '''            winsorized = winsorize_cross_section(\n                values,\n                lower_quantile=self.winsor_lower_quantile,\n                upper_quantile=self.winsor_upper_quantile,\n                eligible=mask,\n            )\n            standardized = cross_sectional_zscore(winsorized, eligible=mask)\n''',
        '''            winsorized = winsorize_cross_section(\n                values.tolist(),\n                lower_quantile=self.winsor_lower_quantile,\n                upper_quantile=self.winsor_upper_quantile,\n                eligible=mask.tolist(),\n            )\n            standardized = cross_sectional_zscore(\n                winsorized.tolist(),\n                eligible=mask.tolist(),\n            )\n''',
    )

    backtest = "src/finagent/backtest/ashare_portfolio.py"
    replace_once(
        backtest,
        '''        for fold in plan.folds:\n            result, rows = self._fold(\n                fold=fold,\n                universe=universe,\n                primary_label=primary_label,\n            )\n            fold_results.append(result)\n            ledger_rows.extend(rows)\n''',
        '''        for fold in plan.folds:\n            fold_result, rows = self._fold(\n                fold=fold,\n                universe=universe,\n                primary_label=primary_label,\n            )\n            fold_results.append(fold_result)\n            ledger_rows.extend(rows)\n''',
    )
    replace_once(
        backtest,
        '''        result = AsharePortfolioValidationResult(\n            mode=mode,\n''',
        '''        final_result = AsharePortfolioValidationResult(\n            mode=mode,\n''',
    )
    replace_once(
        backtest,
        "        return result, tuple(ledger_rows)\n",
        "        return final_result, tuple(ledger_rows)\n",
    )

    script = "scripts/run_ashare_portfolio_validation.py"
    replace_once(
        script,
        '''    if universe_provider.data_version != str(source_policy["data_version"]):\n        raise ValueError(\n            "A4 rebuilt universe policy differs from the frozen A2.6 policy identity"\n        )\n\n''',
        '''    # The A4 policy is rebuilt through the feature-only adapter, so its\n    # identity is deliberately distinct from A2.6 even when the resulting schedule\n    # is semantically equivalent. Both source and derived identities are frozen.\n\n''',
    )
    replace_once(
        script,
        "        universe_policy_version=universe_provider.data_version,\n",
        "        universe_policy_version=str(source_policy[\"data_version\"]),\n",
    )
    replace_once(
        script,
        '''            "fee_schedule": fee_schedule.to_dict(),\n        },\n''',
        '''            "fee_schedule": fee_schedule.to_dict(),\n            "inference_universe_policy_version": universe_provider.data_version,\n        },\n''',
    )


if __name__ == "__main__":
    main()
