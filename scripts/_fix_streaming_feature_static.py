from pathlib import Path

root = Path(__file__).resolve().parents[1]


def patch(path: str, replacements: list[tuple[str, str]]) -> None:
    target = root / path
    text = target.read_text(encoding="utf-8")
    for old, new in replacements:
        if old not in text:
            raise RuntimeError(f"missing patch anchor in {path}: {old!r}")
        text = text.replace(old, new, 1)
    target.write_text(text, encoding="utf-8")


patch(
    "src/finagent/realtime/streaming_resample.py",
    [
        (
            "        if self.bar.complete != (self.observed_minute_count == self.expected_minute_count):\n            if self.bar.complete:\n                raise ValueError(\"complete resampled bar requires full minute coverage\")\n",
            "        if (\n            self.bar.complete\n            and self.observed_minute_count != self.expected_minute_count\n        ):\n            raise ValueError(\"complete resampled bar requires full minute coverage\")\n",
        ),
    ],
)

patch(
    "tests/test_streaming_feature_strategy_v1.py",
    [
        (
            "    AlgorithmRunReport,\n    AlgorithmRunner,\n",
            "    AlgorithmRunner,\n    AlgorithmRunReport,\n",
        ),
        (
            "    StreamingResearchUpdate,\n    StreamingResampledBar,\n",
            "    StreamingResampledBar,\n    StreamingResearchUpdate,\n",
        ),
    ],
)

print("streaming feature static fixes applied")
