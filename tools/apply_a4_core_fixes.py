from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"missing A4 patch anchor: {path}: {old[:80]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    replace_once(
        "src/finagent/backtest/ashare_portfolio.py",
        '''        if not self.selected_feature_digests:\n            raise ValueError("A4 spec requires a frozen factor family")\n        if len(set(self.selected_feature_digests)) != len(self.selected_feature_digests):\n            raise ValueError("A4 selected factor digests must be unique")\n        if not (\n            len(self.selected_feature_digests)\n            == len(self.selected_weights)\n            == len(self.selected_directions)\n        ):\n            raise ValueError("A4 selected factor arrays must align")\n        if any(value not in {-1, 1} for value in self.selected_directions):\n            raise ValueError("A4 selected directions must be +/-1")\n        if any(not math.isfinite(value) or value < 0 for value in self.selected_weights):\n            raise ValueError("A4 selected weights must be finite and non-negative")\n        if abs(sum(self.selected_weights) - 1.0) > 1e-9:\n            raise ValueError("A4 selected weights must sum to one")\n''',
        '''        if len(set(self.selected_feature_digests)) != len(self.selected_feature_digests):\n            raise ValueError("A4 selected factor digests must be unique")\n        if not (\n            len(self.selected_feature_digests)\n            == len(self.selected_weights)\n            == len(self.selected_directions)\n        ):\n            raise ValueError("A4 selected factor arrays must align")\n        if any(value not in {-1, 1} for value in self.selected_directions):\n            raise ValueError("A4 selected directions must be +/-1")\n        if any(not math.isfinite(value) or value < 0 for value in self.selected_weights):\n            raise ValueError("A4 selected weights must be finite and non-negative")\n        if self.selected_feature_digests:\n            if abs(sum(self.selected_weights) - 1.0) > 1e-9:\n                raise ValueError("A4 selected weights must sum to one")\n        elif self.selected_weights or self.selected_directions:\n            raise ValueError("empty A4 factor family requires empty weights/directions")\n''',
    )
    replace_once(
        "src/finagent/backtest/ashare_portfolio.py",
        "eligible = {asset: formation.is_eligible(asset) for asset in universe}",
        "eligible = {asset: bool(formation.eligible.get(asset, False)) for asset in universe}",
    )


if __name__ == "__main__":
    main()
