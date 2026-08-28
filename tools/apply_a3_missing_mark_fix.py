from __future__ import annotations

from pathlib import Path


path = Path(__file__).resolve().parents[1] / "src/finagent/services/ashare_execution.py"
text = path.read_text(encoding="utf-8")
old = '''        nav = state.cash + sum(\n            state.position(asset).total_quantity * snapshot.mark(asset)\n            for asset in state.positions\n        )\n'''
new = '''        # ``mark_to_snapshot`` preserves the last explicit mark when an exact\n        # session row is unavailable. Use that marked account state for valuation,\n        # while tradeability still rejects the order from the exact-session state.\n        nav = state.cash + sum(\n            state.position(asset).total_quantity * state.marks[asset]\n            for asset in state.positions\n        )\n'''
if new not in text:
    if old not in text:
        raise RuntimeError("missing A3 account-mark valuation anchor")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
