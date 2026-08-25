from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ._validation import require_non_empty


class MetricObjective(str, Enum):
    MAXIMIZE = "maximize"
    MINIMIZE = "minimize"


@dataclass(frozen=True, slots=True)
class MetricDefinition:
    """Deterministic semantics for a comparable research metric.

    Metrics are not interpreted from their names.  The objective direction is an
    explicit policy input so adding volatility, drawdown, loss or p-value metrics
    cannot silently reuse the historical "primary high / tie low" convention.
    """

    name: str
    objective: MetricObjective
    unit: str = ""
    valid_min: float | None = None
    valid_max: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", require_non_empty(self.name, "metric name"))
        if self.valid_min is not None and self.valid_max is not None:
            if float(self.valid_max) < float(self.valid_min):
                raise ValueError("metric valid_max cannot be below valid_min")

    def validate(self, value: float) -> float:
        value = float(value)
        if self.valid_min is not None and value < self.valid_min:
            raise ValueError(f"metric {self.name!r} is below valid_min")
        if self.valid_max is not None and value > self.valid_max:
            raise ValueError(f"metric {self.name!r} is above valid_max")
        return value

    def selection_key(self, value: float) -> float:
        value = self.validate(value)
        return -value if self.objective is MetricObjective.MAXIMIZE else value
