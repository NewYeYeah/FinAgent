from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"missing A4 fallback anchor: {old[:100]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    path = "src/finagent/backtest/ashare_portfolio.py"
    replace_once(
        path,
        '''    max_rejected_order_ratio: float = 0.50\n    max_ex_post_participation: float = 0.10\n''',
        '''    max_rejected_order_ratio: float = 0.50\n    max_ex_post_participation: float = 0.10\n    max_cash_fallback_ratio: float = 0.25\n''',
    )
    replace_once(
        path,
        '''            self.max_rejected_order_ratio,\n            self.max_ex_post_participation,\n        )\n''',
        '''            self.max_rejected_order_ratio,\n            self.max_ex_post_participation,\n            self.max_cash_fallback_ratio,\n        )\n''',
    )
    replace_once(
        path,
        '''            self.max_rejected_order_ratio,\n            self.max_ex_post_participation,\n        )\n        if any(not 0.0 <= value <= 1.0 for value in bounded):\n''',
        '''            self.max_rejected_order_ratio,\n            self.max_ex_post_participation,\n            self.max_cash_fallback_ratio,\n        )\n        if any(not 0.0 <= value <= 1.0 for value in bounded):\n''',
    )
    replace_once(
        path,
        '''            "max_rejected_order_ratio": self.max_rejected_order_ratio,\n            "max_ex_post_participation": self.max_ex_post_participation,\n        }\n''',
        '''            "max_rejected_order_ratio": self.max_rejected_order_ratio,\n            "max_ex_post_participation": self.max_ex_post_participation,\n            "max_cash_fallback_ratio": self.max_cash_fallback_ratio,\n        }\n''',
    )

    replace_once(
        path,
        '''    rebalanced: bool\n    target_id: str\n    net_nav: float\n''',
        '''    rebalanced: bool\n    cash_fallback: bool\n    target_id: str\n    net_nav: float\n''',
    )
    replace_once(
        path,
        '''            "rebalanced": self.rebalanced,\n            "target_id": self.target_id,\n''',
        '''            "rebalanced": self.rebalanced,\n            "cash_fallback": self.cash_fallback,\n            "target_id": self.target_id,\n''',
    )

    replace_once(
        path,
        '''    rejected_order_count: int\n    rejected_order_ratio: float\n    hac_tstat: float\n''',
        '''    rejected_order_count: int\n    rejected_order_ratio: float\n    rebalance_count: int\n    cash_fallback_count: int\n    cash_fallback_ratio: float\n    hac_tstat: float\n''',
    )
    replace_once(
        path,
        '''            "rejected_order_count": self.rejected_order_count,\n            "rejected_order_ratio": self.rejected_order_ratio,\n            "hac_tstat": self.hac_tstat,\n''',
        '''            "rejected_order_count": self.rejected_order_count,\n            "rejected_order_ratio": self.rejected_order_ratio,\n            "rebalance_count": self.rebalance_count,\n            "cash_fallback_count": self.cash_fallback_count,\n            "cash_fallback_ratio": self.cash_fallback_ratio,\n            "hac_tstat": self.hac_tstat,\n''',
    )

    replace_once(
        path,
        '''            net_signal_state = self.ledger.roll_to_session(net_state, session_date)\n            gross_signal_state = self.ledger.roll_to_session(gross_state, session_date)\n            signal_asof = execution_snapshot.asof - timedelta(microseconds=1)\n''',
        '''            net_signal_state = self.ledger.roll_to_session(net_state, session_date)\n            gross_signal_state = self.ledger.roll_to_session(gross_state, session_date)\n            net_pretrade_state = self.ledger.mark_to_snapshot(\n                net_signal_state,\n                execution_snapshot,\n            )\n            gross_pretrade_state = self.ledger.mark_to_snapshot(\n                gross_signal_state,\n                execution_snapshot,\n            )\n            signal_asof = execution_snapshot.asof - timedelta(microseconds=1)\n''',
    )
    replace_once(
        path,
        '''            else:\n                net_open_state = self.ledger.mark_to_snapshot(\n                    net_signal_state,\n                    execution_snapshot,\n                )\n                gross_open_state = self.ledger.mark_to_snapshot(\n                    gross_signal_state,\n                    execution_snapshot,\n                )\n\n            net_state = self._mark_to_close(self.ledger, net_open_state, close_snapshot)\n''',
        '''            else:\n                net_open_state = net_pretrade_state\n                gross_open_state = gross_pretrade_state\n\n            cash_fallback = bool(\n                target is not None and target.source.name == "a4_cash_fallback"\n            )\n            execution_target_deviation = (\n                self._implementation_shortfall(net_open_state, target)\n                if target is not None\n                else 0.0\n            )\n            net_state = self._mark_to_close(self.ledger, net_open_state, close_snapshot)\n''',
    )
    replace_once(
        path,
        '''            target_turnover = (\n                self._target_turnover(net_signal_state, target)\n                if target is not None\n                else 0.0\n            )\n            shortfall = (\n                self._implementation_shortfall(net_state, target)\n                if target is not None\n                else 0.0\n            )\n''',
        '''            target_turnover = (\n                self._target_turnover(net_pretrade_state, target)\n                if target is not None\n                else 0.0\n            )\n            shortfall = execution_target_deviation\n''',
    )
    replace_once(
        path,
        '''                rebalanced=rebalanced,\n                target_id=target_id,\n''',
        '''                rebalanced=rebalanced,\n                cash_fallback=cash_fallback,\n                target_id=target_id,\n''',
    )

    replace_once(
        path,
        '''        denominator = order_count + rejected\n        rejected_ratio = rejected / denominator if denominator else 0.0\n        reasons: Counter[str] = Counter()\n''',
        '''        denominator = order_count + rejected\n        rejected_ratio = rejected / denominator if denominator else 0.0\n        rebalance_count = sum(\n            point.rebalanced for fold in folds for point in fold.points\n        )\n        cash_fallback_count = sum(\n            point.cash_fallback for fold in folds for point in fold.points\n        )\n        cash_fallback_ratio = (\n            cash_fallback_count / rebalance_count if rebalance_count else 0.0\n        )\n        reasons: Counter[str] = Counter()\n''',
    )
    replace_once(
        path,
        '''            rejected_order_count=rejected,\n            rejected_order_ratio=rejected_ratio,\n            hac_tstat=hac_tstat,\n''',
        '''            rejected_order_count=rejected,\n            rejected_order_ratio=rejected_ratio,\n            rebalance_count=rebalance_count,\n            cash_fallback_count=cash_fallback_count,\n            cash_fallback_ratio=cash_fallback_ratio,\n            hac_tstat=hac_tstat,\n''',
    )
    replace_once(
        path,
        '''            (\n                aggregate.maximum_ex_post_participation\n                <= policy.max_ex_post_participation,\n                "EX_POST_PARTICIPATION_ABOVE_THRESHOLD",\n            ),\n        )\n''',
        '''            (\n                aggregate.maximum_ex_post_participation\n                <= policy.max_ex_post_participation,\n                "EX_POST_PARTICIPATION_ABOVE_THRESHOLD",\n            ),\n            (\n                aggregate.cash_fallback_ratio <= policy.max_cash_fallback_ratio,\n                "CASH_FALLBACK_RATIO_ABOVE_THRESHOLD",\n            ),\n        )\n''',
    )

    cli = "scripts/run_ashare_portfolio_validation.py"
    replace_once(
        cli,
        '''        max_ex_post_participation=float(\n            values.get("policy_max_ex_post_participation", 0.10)\n        ),\n    )\n''',
        '''        max_ex_post_participation=float(\n            values.get("policy_max_ex_post_participation", 0.10)\n        ),\n        max_cash_fallback_ratio=float(\n            values.get("policy_max_cash_fallback_ratio", 0.25)\n        ),\n    )\n''',
    )

    config = "configs/execution/ashare_portfolio_validation_a4.example.toml"
    replace_once(
        config,
        '''policy_max_rejected_order_ratio = 0.50\n# Ex-post only: full-day volume is not used to decide fills.\npolicy_max_ex_post_participation = 0.10\n''',
        '''policy_max_rejected_order_ratio = 0.50\npolicy_max_cash_fallback_ratio = 0.25\n# Ex-post only: full-day volume is not used to decide fills.\npolicy_max_ex_post_participation = 0.10\n''',
    )


if __name__ == "__main__":
    main()
