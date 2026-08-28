from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"missing A4 accounting anchor: {old[:120]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    path = "src/finagent/backtest/ashare_portfolio.py"
    replace_once(
        path,
        '''    source_program_result_id: str\n    source_program_spec_id: str\n''',
        '''    source_program_result_id: str\n    source_report_digest: str\n    source_program_spec_id: str\n''',
    )
    replace_once(
        path,
        '''            "source_program_result_id",\n            "source_program_spec_id",\n''',
        '''            "source_program_result_id",\n            "source_report_digest",\n            "source_program_spec_id",\n''',
    )
    replace_once(
        path,
        '''            "source_program_result_id": self.source_program_result_id,\n            "source_program_spec_id": self.source_program_spec_id,\n''',
        '''            "source_program_result_id": self.source_program_result_id,\n            "source_report_digest": self.source_report_digest,\n            "source_program_spec_id": self.source_program_spec_id,\n''',
    )

    replace_once(
        path,
        '''    order_count: int\n    fill_count: int\n    rejected_order_count: int\n''',
        '''    desired_order_count: int\n    order_count: int\n    fill_count: int\n    rejected_order_count: int\n''',
    )
    replace_once(
        path,
        '''        counts = (self.order_count, self.fill_count, self.rejected_order_count)\n''',
        '''        counts = (\n            self.desired_order_count,\n            self.order_count,\n            self.fill_count,\n            self.rejected_order_count,\n        )\n''',
    )
    replace_once(
        path,
        '''            "implementation_shortfall": self.implementation_shortfall,\n            "order_count": self.order_count,\n''',
        '''            "implementation_shortfall": self.implementation_shortfall,\n            "desired_order_count": self.desired_order_count,\n            "order_count": self.order_count,\n''',
    )

    replace_once(
        path,
        '''    order_count: int\n    fill_count: int\n    rejected_order_count: int\n    rejected_order_ratio: float\n''',
        '''    desired_order_count: int\n    order_count: int\n    fill_count: int\n    rejected_order_count: int\n    rejected_order_ratio: float\n''',
    )
    replace_once(
        path,
        '''            "worst_fold_net_sharpe": self.worst_fold_net_sharpe,\n            "order_count": self.order_count,\n''',
        '''            "worst_fold_net_sharpe": self.worst_fold_net_sharpe,\n            "desired_order_count": self.desired_order_count,\n            "order_count": self.order_count,\n''',
    )

    replace_once(
        path,
        '''            order_count = len(net_cycle.execution.orders) if net_cycle is not None else 0\n            fill_count = len(fills)\n            rejected_count = (\n''',
        '''            desired_order_count = (\n                len(net_cycle.compilation.decisions) if net_cycle is not None else 0\n            )\n            order_count = len(net_cycle.execution.orders) if net_cycle is not None else 0\n            fill_count = len(fills)\n            rejected_count = (\n''',
    )
    replace_once(
        path,
        '''                implementation_shortfall=shortfall,\n                order_count=order_count,\n''',
        '''                implementation_shortfall=shortfall,\n                desired_order_count=desired_order_count,\n                order_count=order_count,\n''',
    )
    replace_once(
        path,
        '''                average_implementation_shortfall=float(\n                    np.mean([point.implementation_shortfall for point in points])\n                ),\n''',
        '''                average_implementation_shortfall=float(\n                    np.mean(\n                        [\n                            point.implementation_shortfall\n                            for point in points\n                            if point.rebalanced\n                        ]\n                    )\n                ),\n''',
    )

    replace_once(
        path,
        '''        order_count = sum(point.order_count for fold in folds for point in fold.points)\n        fill_count = sum(point.fill_count for fold in folds for point in fold.points)\n''',
        '''        desired_order_count = sum(\n            point.desired_order_count for fold in folds for point in fold.points\n        )\n        order_count = sum(point.order_count for fold in folds for point in fold.points)\n        fill_count = sum(point.fill_count for fold in folds for point in fold.points)\n''',
    )
    replace_once(
        path,
        '''        denominator = order_count + rejected\n        rejected_ratio = rejected / denominator if denominator else 0.0\n''',
        '''        rejected_ratio = (\n            rejected / desired_order_count if desired_order_count else 0.0\n        )\n''',
    )
    replace_once(
        path,
        '''            average_implementation_shortfall=float(\n                np.mean([fold.average_implementation_shortfall for fold in folds])\n            ),\n''',
        '''            average_implementation_shortfall=float(\n                np.mean(\n                    [\n                        point.implementation_shortfall\n                        for fold in folds\n                        for point in fold.points\n                        if point.rebalanced\n                    ]\n                )\n            ),\n''',
    )
    replace_once(
        path,
        '''            worst_fold_net_sharpe=min(fold.net_metrics.sharpe for fold in folds),\n            order_count=order_count,\n''',
        '''            worst_fold_net_sharpe=min(fold.net_metrics.sharpe for fold in folds),\n            desired_order_count=desired_order_count,\n            order_count=order_count,\n''',
    )

    cli = "scripts/run_ashare_portfolio_validation.py"
    replace_once(
        cli,
        '''import argparse\nimport json\nimport tomllib\n''',
        '''import argparse\nimport hashlib\nimport json\nimport tomllib\n''',
    )
    replace_once(
        cli,
        '''def _mapping(value: object, name: str) -> Mapping[str, object]:\n''',
        '''def _canonical_digest(value: object) -> str:\n    encoded = json.dumps(\n        value,\n        sort_keys=True,\n        separators=(",", ":"),\n        ensure_ascii=False,\n        allow_nan=False,\n    ).encode()\n    return hashlib.sha256(encoded).hexdigest()\n\n\ndef _mapping(value: object, name: str) -> Mapping[str, object]:\n''',
    )
    replace_once(
        cli,
        '''        source_program_result_id=str(source["program_result_id"]),\n        source_program_spec_id=str(program["spec_id"]),\n''',
        '''        source_program_result_id=str(source["program_result_id"]),\n        source_report_digest=_canonical_digest(source),\n        source_program_spec_id=str(program["spec_id"]),\n''',
    )

    test = "tests/test_ashare_portfolio_validation_a4.py"
    replace_once(
        test,
        '''        source_program_result_id="program-result",\n        source_program_spec_id="program-spec",\n''',
        '''        source_program_result_id="program-result",\n        source_report_digest="a" * 64,\n        source_program_spec_id="program-spec",\n''',
    )
    replace_once(
        test,
        '''    assert payload["aggregate"]["total_slippage"] >= 0\n    assert payload["ledger_digest"].startswith("a4-execution-ledger-")\n''',
        '''    assert payload["aggregate"]["total_slippage"] >= 0\n    assert payload["aggregate"]["desired_order_count"] >= (\n        payload["aggregate"]["rejected_order_count"]\n    )\n    assert 0.0 <= payload["aggregate"]["cash_fallback_ratio"] <= 1.0\n    assert payload["validation_spec"]["source_report_digest"]\n    assert payload["ledger_digest"].startswith("a4-execution-ledger-")\n''',
    )


if __name__ == "__main__":
    main()
