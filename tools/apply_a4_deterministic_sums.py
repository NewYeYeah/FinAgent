from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"missing deterministic-sum anchor: {old[:100]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    path = "src/finagent/backtest/ashare_portfolio.py"
    replace_once(
        path,
        '''        current = cls._weights(state)\n        assets = set(current) | set(target.weights)\n        risky = sum(\n            abs(target.weights.get(asset, 0.0) - current.get(asset, 0.0))\n            for asset in assets\n        )\n        current_cash = state.cash / state.nav\n        return 0.5 * (risky + abs(target.cash_weight - current_cash))\n''',
        '''        current = cls._weights(state)\n        assets = sorted(set(current) | set(target.weights))\n        risky = math.fsum(\n            abs(target.weights.get(asset, 0.0) - current.get(asset, 0.0))\n            for asset in assets\n        )\n        current_cash = state.cash / state.nav\n        return 0.5 * math.fsum(\n            (risky, abs(target.cash_weight - current_cash))\n        )\n''',
    )
    replace_once(
        path,
        '''        actual = cls._weights(state)\n        assets = set(actual) | set(target.weights)\n        risky = sum(\n            abs(target.weights.get(asset, 0.0) - actual.get(asset, 0.0))\n            for asset in assets\n        )\n        actual_cash = state.cash / state.nav\n        return 0.5 * (risky + abs(target.cash_weight - actual_cash))\n''',
        '''        actual = cls._weights(state)\n        assets = sorted(set(actual) | set(target.weights))\n        risky = math.fsum(\n            abs(target.weights.get(asset, 0.0) - actual.get(asset, 0.0))\n            for asset in assets\n        )\n        actual_cash = state.cash / state.nav\n        return 0.5 * math.fsum(\n            (risky, abs(target.cash_weight - actual_cash))\n        )\n''',
    )


if __name__ == "__main__":
    main()
