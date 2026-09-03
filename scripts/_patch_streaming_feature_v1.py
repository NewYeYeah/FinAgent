from pathlib import Path

root = Path(__file__).resolve().parents[1]
path = root / "tests" / "test_streaming_feature_strategy_v1.py"
text = path.read_text(encoding="utf-8")
replacements = [
    (
        "    QuoteEvent,\n    RealtimeEventKind,\n",
        "    QuoteEvent,\n    RealtimeEventKind,\n    RealtimeProjector,\n",
    ),
    (
        "    streamed_15m = _flatten_resampled(updates, 15 * 60)\n    assert len(streamed_15m) == 20\n",
        "    streamed_5m = _flatten_resampled(updates, 5 * 60)\n    streamed_15m = _flatten_resampled(updates, 15 * 60)\n    streamed_30m = _flatten_resampled(updates, 30 * 60)\n    assert len(streamed_5m) == 60\n    assert len(streamed_15m) == 20\n    assert len(streamed_30m) == 10\n",
    ),
    (
        "    calendar = _calendar(minutes=20)\n",
        "    calendar = _calendar(minutes=30)\n",
    ),
    (
        "    assert algorithm.on_event(quote, AlgorithmRunner()._projector.snapshot()) is None\n",
        "    assert algorithm.on_event(quote, RealtimeProjector().snapshot()) is None\n",
    ),
]
for old, new in replacements:
    if old not in text:
        raise RuntimeError(f"missing patch anchor: {old!r}")
    text = text.replace(old, new, 1)
path.write_text(text, encoding="utf-8")
print("streaming feature v1 test patch applied")
