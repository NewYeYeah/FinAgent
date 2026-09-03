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
    "src/finagent/realtime/sources.py",
    [
        (
            "from enum import StrEnum\nfrom typing import AsyncIterator, Protocol, runtime_checkable\n",
            "from collections.abc import AsyncIterator\nfrom enum import StrEnum\nfrom typing import Protocol, runtime_checkable\n",
        ),
        (
            "        if self.timing_class is FeedTimingClass.DELAYED:\n            if self.observed_delay_seconds is None or self.observed_delay_seconds <= 0:\n                raise ValueError(\"DELAYED timing profile requires observed_delay_seconds > 0\")\n",
            "        if (\n            self.timing_class is FeedTimingClass.DELAYED\n            and (self.observed_delay_seconds is None or self.observed_delay_seconds <= 0)\n        ):\n            raise ValueError(\"DELAYED timing profile requires observed_delay_seconds > 0\")\n",
        ),
    ],
)

patch(
    "src/finagent/realtime/database_replay.py",
    [
        (
            "from collections.abc import Awaitable, Callable\n",
            "from collections.abc import AsyncIterator, Awaitable, Callable\n",
        ),
        (
            "    ) -> object:\n        query = self._query(subscription)\n",
            "    ) -> AsyncIterator[CanonicalRealtimeEvent]:\n        query = self._query(subscription)\n",
        ),
        (
            "        emitted = 0\n        sequence = 0\n        for row in iter_plan_rows(\n",
            "        emitted = 0\n        for sequence, row in enumerate(iter_plan_rows(\n",
        ),
        (
            "            temp_directory=self._temp_directory,\n        ):\n",
            "            temp_directory=self._temp_directory,\n        )):\n",
        ),
        (
            "            emitted += 1\n            sequence += 1\n",
            "            emitted = sequence + 1\n",
        ),
    ],
)

patch(
    "src/finagent/realtime/mt5_source.py",
    [
        (
            "from collections.abc import Awaitable, Callable\n",
            "from collections.abc import AsyncIterator, Awaitable, Callable\n",
        ),
        (
            "    ) -> object:\n        if subscription.start is not None or subscription.end is not None:\n",
            "    ) -> AsyncIterator[CanonicalRealtimeEvent]:\n        if subscription.start is not None or subscription.end is not None:\n",
        ),
    ],
)

patch(
    "src/finagent/realtime/__init__.py",
    [
        (
            "from finagent.realtime.algorithm import (\n    AlgorithmRunReport,\n    AlgorithmRunner,\n    StreamingAlgorithm,\n)\n",
            "from finagent.realtime.algorithm import (\n    AlgorithmRunner,\n    AlgorithmRunReport,\n    StreamingAlgorithm,\n)\n",
        ),
    ],
)

print("streaming source v1 static patch applied")
