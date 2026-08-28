from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"missing A4 source-guard anchor: {old[:100]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    backtest = "src/finagent/backtest/ashare_portfolio.py"
    replace_once(
        backtest,
        '''        lookback = max(alpha_model.min_lookback, self.config.risk_lookback)\n        fields = tuple(dict.fromkeys((*alpha_model.required_features, "simple_return_1")))\n''',
        '''        if alpha_model.calibration.non_negative_slope <= 1e-15:\n            return self._cash_target(\n                asof=signal_asof,\n                state=state,\n                reason="NONPOSITIVE_ALPHA_CALIBRATION_SLOPE",\n            )\n        lookback = max(alpha_model.min_lookback, self.config.risk_lookback)\n        fields = tuple(dict.fromkeys((*alpha_model.required_features, "simple_return_1")))\n''',
    )

    script = "scripts/run_ashare_portfolio_validation.py"
    replace_once(
        script,
        '''    return AshareExpandingWalkForwardPlan(\n        folds=tuple(folds),\n        reserve=_time_range(raw_plan["reserve"], "walk_forward reserve"),\n    )\n''',
        '''    plan = AshareExpandingWalkForwardPlan(\n        folds=tuple(folds),\n        reserve=_time_range(raw_plan["reserve"], "walk_forward reserve"),\n    )\n    if str(raw_plan.get("plan_id", "")) != plan.plan_id:\n        raise ValueError("A2.6 walk-forward content differs from its frozen plan_id")\n    return plan\n''',
    )
    replace_once(
        script,
        '''    return AshareRobustFactorSelection(\n        walk_forward_report_id=str(raw["walk_forward_report_id"]),\n        gate_report_id=str(raw["gate_report_id"]),\n        status=str(raw["status"]),\n        config=AshareRobustSelectorConfig(\n            max_factors=int(raw_config.get("max_factors", 3)),\n            max_abs_factor_correlation=float(\n                raw_config.get("max_abs_factor_correlation", 0.85)\n            ),\n            quality_power=float(raw_config.get("quality_power", 1.0)),\n        ),\n        components=tuple(components),\n    )\n''',
        '''    selection = AshareRobustFactorSelection(\n        walk_forward_report_id=str(raw["walk_forward_report_id"]),\n        gate_report_id=str(raw["gate_report_id"]),\n        status=str(raw["status"]),\n        config=AshareRobustSelectorConfig(\n            max_factors=int(raw_config.get("max_factors", 3)),\n            max_abs_factor_correlation=float(\n                raw_config.get("max_abs_factor_correlation", 0.85)\n            ),\n            quality_power=float(raw_config.get("quality_power", 1.0)),\n        ),\n        components=tuple(components),\n    )\n    if str(raw.get("selection_id", "")) != selection.selection_id:\n        raise ValueError("A2.6 factor-family content differs from its selection_id")\n    return selection\n''',
    )


if __name__ == "__main__":
    main()
