from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise RuntimeError(f"missing A3 patch anchor: {path}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "src/finagent/data/ashare_execution.py",
    "    def _positive_or_none(value: object) -> float | None:\n",
    "    def _positive_or_none(value: Any) -> float | None:\n",
)
replace_once(
    "src/finagent/data/ashare_execution.py",
    "    def _finite(value: object, default: float = 0.0) -> float:\n",
    "    def _finite(value: Any, default: float = 0.0) -> float:\n",
)
replace_once(
    "src/finagent/data/ashare_execution.py",
    '''        if any(value is None for value in values):\n            return True\n        open_, high, low, close = (float(value) for value in values)\n        return high < max(open_, close) or low > min(open_, close) or high < low\n''',
    '''        clean = tuple(value for value in values if value is not None)\n        if len(clean) != 4:\n            return True\n        open_, high, low, close = clean\n        return high < max(open_, close) or low > min(open_, close) or high < low\n''',
)
replace_once(
    "src/finagent/services/ashare_execution.py",
    '''                else:\n                    buy_specs.append((desired, 0, [blocked]))\n                continue\n\n            board = market.board\n''',
    '''                else:\n                    buy_specs.append((desired, 0, [blocked]))\n                continue\n\n            assert price is not None\n            board = market.board\n''',
)
