from __future__ import annotations

from pathlib import Path


def test_replay_first_surface_has_no_live_mt5_mutation_calls() -> None:
    root = Path(__file__).resolve().parents[1]
    sources = (
        root / "src/finagent/brokers/mt5/paper_replay.py",
        root / "scripts/smoke_mt5_paper_replay_operations.py",
    )
    forbidden = (
        "order_send(",
        "symbol_select(",
        "market_book_add(",
        "positions_get(",
        "MetaTrader5ReadOnlyClient(",
    )
    for path in sources:
        text = path.read_text(encoding="utf-8")
        assert not [item for item in forbidden if item in text]
