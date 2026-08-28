from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise RuntimeError(f"missing patch anchor: {path}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "src/finagent/services/ashare_execution.py",
    '''        if board is AshareBoard.SSE_STAR:\n            quantity = integer if integer >= self.star_minimum_buy else 0\n        else:\n            quantity = (integer // self.regular_lot_size) * self.regular_lot_size\n''',
    '''        if board is AshareBoard.SSE_STAR:\n            quantity = integer if integer >= self.star_minimum_buy else 0\n        elif board is AshareBoard.BSE:\n            quantity = integer if integer >= self.regular_lot_size else 0\n        else:\n            quantity = (integer // self.regular_lot_size) * self.regular_lot_size\n''',
)
replace_once(
    "src/finagent/services/ashare_execution.py",
    '''        elif board is AshareBoard.SSE_STAR:\n            quantity = capped if capped >= self.star_minimum_buy else 0\n        else:\n            lot = self.regular_lot_size\n''',
    '''        elif board is AshareBoard.SSE_STAR:\n            quantity = capped if capped >= self.star_minimum_buy else 0\n        elif board is AshareBoard.BSE:\n            quantity = capped if capped >= self.regular_lot_size else 0\n        else:\n            lot = self.regular_lot_size\n''',
)
replace_once(
    "src/finagent/services/ashare_execution.py",
    '''        if board is AshareBoard.SSE_STAR:\n            minimum = self.lot_policy.star_minimum_buy\n            if maximum < minimum:\n''',
    '''        if board in {AshareBoard.SSE_STAR, AshareBoard.BSE}:\n            minimum = (\n                self.lot_policy.star_minimum_buy\n                if board is AshareBoard.SSE_STAR\n                else self.lot_policy.regular_lot_size\n            )\n            if maximum < minimum:\n''',
)
replace_once(
    "tests/test_ashare_execution_a3.py",
    '''    assert policy.round_buy(AshareBoard.BSE, 257)[0] == 200\n    assert policy.round_sell(AshareBoard.SSE_MAIN, 160, 250)[0] == 150\n''',
    '''    assert policy.round_buy(AshareBoard.BSE, 99)[0] == 0\n    assert policy.round_buy(AshareBoard.BSE, 257)[0] == 257\n    assert policy.round_sell(AshareBoard.SSE_MAIN, 160, 250)[0] == 150\n''',
)
replace_once(
    "tests/test_ashare_execution_a3.py",
    '''    assert policy.round_sell(AshareBoard.SSE_STAR, 199, 500)[0] == 0\n    assert policy.round_sell(AshareBoard.SSE_STAR, 250, 500)[0] == 250\n''',
    '''    assert policy.round_sell(AshareBoard.SSE_STAR, 199, 500)[0] == 0\n    assert policy.round_sell(AshareBoard.SSE_STAR, 250, 500)[0] == 250\n    assert policy.round_sell(AshareBoard.BSE, 99, 500)[0] == 0\n    assert policy.round_sell(AshareBoard.BSE, 157, 500)[0] == 157\n    assert policy.round_sell(AshareBoard.BSE, 75, 75)[0] == 75\n''',
)
replace_once(
    "docs/guides/ashare-execution.md",
    '''- SSE/SZSE main board, ChiNext and BSE buys: 100-share lots;\n- STAR buys: at least 200 shares, then integer-share increments;\n- regular-board sells: 100-share lots plus the existing under-100 odd-lot remainder, which must remain unsplit;\n- STAR sells: at least 200 shares unless the full remaining balance is below 200.\n''',
    '''- SSE/SZSE main board and ChiNext buys: 100-share lots;\n- STAR buys: at least 200 shares, then integer-share increments;\n- BSE buys: at least 100 shares, then integer-share increments;\n- SSE/SZSE regular-board sells: 100-share lots plus the existing under-100 odd-lot remainder, which must remain unsplit;\n- STAR sells: at least 200 shares unless the full remaining balance is below 200;\n- BSE sells: at least 100 shares unless the full remaining balance is below 100.\n''',
)
