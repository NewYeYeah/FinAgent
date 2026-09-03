from pathlib import Path

# Temporary branch-local patcher; removed before merge.
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
            "from finagent.data.minute_transform import CalendarSessionizedMinuteStore, SessionResampledMinuteStore\n",
            "from finagent.data.minute_transform import (\n    CalendarSessionizedMinuteStore,\n    SessionResampledMinuteStore,\n)\n",
        ),
        (
            "    AlgorithmRunner,\n    BarEvent,\n",
            "    AlgorithmRunReport,\n    AlgorithmRunner,\n    BarEvent,\n",
        ),
        (
            "    StreamingResearchUpdate,\n    USBaselineStreamingAlgorithm,\n",
            "    StreamingResearchUpdate,\n    StreamingResampledBar,\n    USBaselineStreamingAlgorithm,\n",
        ),
        (
            "def _updates(report: object) -> tuple[StreamingResearchUpdate, ...]:\n    outputs = getattr(report, \"outputs\")\n    return tuple(item for item in outputs if isinstance(item, StreamingResearchUpdate))\n",
            "def _updates(report: AlgorithmRunReport) -> tuple[StreamingResearchUpdate, ...]:\n    return tuple(\n        item for item in report.outputs if isinstance(item, StreamingResearchUpdate)\n    )\n",
        ),
        (
            "    interval_seconds: int,\n) -> tuple[object, ...]:\n",
            "    interval_seconds: int,\n) -> tuple[StreamingResampledBar, ...]:\n",
        ),
    ],
)

print("streaming feature v1 static patch applied")
