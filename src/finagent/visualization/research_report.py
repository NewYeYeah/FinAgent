from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence


class ResearchReportError(ValueError):
    """Raised when a research report cannot be displayed safely."""


def _mapping(value: object, name: str, *, required: bool = True) -> Mapping[str, Any]:
    if value is None and not required:
        return {}
    if not isinstance(value, Mapping):
        raise ResearchReportError(f"{name} must be a JSON object")
    return value


def _sequence(value: object, name: str, *, required: bool = True) -> Sequence[Any]:
    if value is None and not required:
        return ()
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ResearchReportError(f"{name} must be a JSON array")
    return value


def _text(value: object, default: str = "") -> str:
    return default if value is None else str(value)


def _number(value: object, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ResearchReportError(f"expected numeric report value, got {value!r}") from exc


def _integer(value: object, default: int = 0) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ResearchReportError(f"expected integer report value, got {value!r}") from exc


def _candidate_map(report: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    values = _sequence(report.get("candidates"), "factor report candidates")
    output: dict[str, Mapping[str, Any]] = {}
    for raw in values:
        candidate = _mapping(raw, "factor report candidate")
        digest = _text(candidate.get("feature_digest")).strip()
        if not digest:
            raise ResearchReportError("factor report candidate is missing feature_digest")
        if digest in output:
            raise ResearchReportError(f"duplicate factor candidate digest: {digest}")
        output[digest] = candidate
    return output


def _stability_map(report: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    values = _sequence(report.get("candidates"), "stability candidates", required=False)
    output: dict[str, Mapping[str, Any]] = {}
    for raw in values:
        candidate = _mapping(raw, "stability candidate")
        digest = _text(candidate.get("feature_digest")).strip()
        if digest:
            output[digest] = candidate
    return output


def _primary(candidate: Mapping[str, Any]) -> Mapping[str, Any]:
    label = _text(candidate.get("primary_label")).strip()
    horizons = _mapping(
        candidate.get("horizon_diagnostics"),
        "candidate horizon_diagnostics",
        required=False,
    )
    if label and label in horizons:
        return _mapping(horizons[label], f"horizon diagnostics {label}")
    if horizons:
        first = next(iter(horizons.values()))
        return _mapping(first, "primary horizon diagnostics")
    return {}


@dataclass(frozen=True, slots=True)
class CandidateSnapshot:
    feature_id: str
    feature_digest: str
    hypothesis: str
    input_fields: tuple[str, ...]
    lookback: int
    generator_id: str
    selected: bool
    weight: float
    direction: int
    development: Mapping[str, Any]
    validation: Mapping[str, Any]
    development_stability: Mapping[str, Any]
    validation_stability: Mapping[str, Any]
    validation_multiplicity: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "development", MappingProxyType(dict(self.development)))
        object.__setattr__(self, "validation", MappingProxyType(dict(self.validation)))
        object.__setattr__(
            self,
            "development_stability",
            MappingProxyType(dict(self.development_stability)),
        )
        object.__setattr__(
            self,
            "validation_stability",
            MappingProxyType(dict(self.validation_stability)),
        )
        object.__setattr__(
            self,
            "validation_multiplicity",
            MappingProxyType(dict(self.validation_multiplicity)),
        )

    @property
    def development_primary(self) -> Mapping[str, Any]:
        return _primary(self.development)

    @property
    def validation_primary(self) -> Mapping[str, Any]:
        return _primary(self.validation)

    def metric_row(self) -> dict[str, object]:
        dev_primary = self.development_primary
        val_primary = self.validation_primary
        dev_quantile = _mapping(
            self.development.get("quantile_diagnostics"),
            "development quantile diagnostics",
            required=False,
        )
        val_quantile = _mapping(
            self.validation.get("quantile_diagnostics"),
            "validation quantile diagnostics",
            required=False,
        )
        hac = _mapping(
            self.validation_stability.get("hac"),
            "validation HAC",
            required=False,
        )
        bootstrap = _mapping(
            self.validation_stability.get("block_bootstrap"),
            "validation block bootstrap",
            required=False,
        )
        return {
            "feature_id": self.feature_id,
            "feature_digest": self.feature_digest,
            "selected": self.selected,
            "weight": self.weight,
            "direction": self.direction,
            "development_rank_ic": _number(dev_primary.get("rank_ic")),
            "development_rank_icir": _number(dev_primary.get("rank_icir")),
            "validation_rank_ic": _number(val_primary.get("rank_ic")),
            "validation_rank_icir": _number(val_primary.get("rank_icir")),
            "development_long_short_sharpe": _number(
                dev_quantile.get("long_short_sharpe")
            ),
            "validation_long_short_sharpe": _number(
                val_quantile.get("long_short_sharpe")
            ),
            "development_coverage": _number(self.development.get("coverage")),
            "validation_coverage": _number(self.validation.get("coverage")),
            "validation_sign_consistency": _number(
                self.validation_stability.get("sign_consistency_ratio")
            ),
            "validation_quantile_monotonicity": _number(
                self.validation_stability.get("quantile_monotonicity")
            ),
            "validation_hac_pvalue": _number(hac.get("pvalue"), 1.0),
            "validation_bootstrap_pvalue": _number(bootstrap.get("pvalue"), 1.0),
            "validation_holm_pvalue": _number(
                self.validation_multiplicity.get("holm_adjusted_pvalue"), 1.0
            ),
            "validation_bh_qvalue": _number(
                self.validation_multiplicity.get("bh_qvalue"), 1.0
            ),
        }


@dataclass(frozen=True, slots=True)
class ResearchReportView:
    payload: Mapping[str, Any]
    source: str = ""
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        payload = dict(self.payload)
        schema = _text(payload.get("schema_version")).strip()
        if not schema.startswith("finagent.ashare-factor-research-acceptance.v"):
            raise ResearchReportError(
                "unsupported report schema; expected an A-share factor acceptance report"
            )
        denominator = _sequence(payload.get("candidate_denominator"), "candidate_denominator")
        if not denominator:
            raise ResearchReportError("candidate_denominator cannot be empty")
        object.__setattr__(self, "payload", MappingProxyType(payload))
        object.__setattr__(self, "warnings", tuple(self.warnings))
        self._validate_denominators()

    @property
    def schema_version(self) -> str:
        return _text(self.payload.get("schema_version"))

    @property
    def acceptance_id(self) -> str:
        return _text(self.payload.get("acceptance_id"))

    @property
    def mode(self) -> str:
        return _text(self.payload.get("mode"), "unknown")

    @property
    def data_version(self) -> str:
        return _text(self.payload.get("data_version"))

    @property
    def system_passed(self) -> bool:
        system = _mapping(
            self.payload.get("system_acceptance"),
            "system_acceptance",
            required=False,
        )
        if system:
            return bool(system.get("passed"))
        return bool(self.payload.get("passed"))

    @property
    def research_outcome(self) -> Mapping[str, Any]:
        return _mapping(
            self.payload.get("research_outcome"),
            "research_outcome",
            required=False,
        )

    @property
    def research_status(self) -> str:
        outcome = self.research_outcome
        if outcome:
            return _text(outcome.get("status"), "UNKNOWN")
        return "LEGACY_REPORT_NO_RESEARCH_VERDICT"

    @property
    def promotion_eligible(self) -> bool:
        return bool(self.research_outcome.get("promotion_eligible", False))

    @property
    def reserve(self) -> Mapping[str, Any]:
        return _mapping(self.payload.get("reserve"), "reserve", required=False)

    @property
    def candidate_universe(self) -> Mapping[str, Any]:
        return _mapping(self.payload.get("candidate_universe"), "candidate_universe")

    @property
    def universe_policy(self) -> Mapping[str, Any]:
        return _mapping(self.payload.get("universe_policy"), "universe_policy")

    @property
    def development_report(self) -> Mapping[str, Any]:
        return _mapping(self.payload.get("development_report"), "development_report")

    @property
    def validation_report(self) -> Mapping[str, Any]:
        return _mapping(self.payload.get("validation_report"), "validation_report")

    @property
    def frozen_ensemble(self) -> Mapping[str, Any]:
        return _mapping(self.payload.get("frozen_ensemble"), "frozen_ensemble")

    @property
    def validation_ensemble(self) -> Mapping[str, Any]:
        return _mapping(self.payload.get("validation_ensemble"), "validation_ensemble")

    @property
    def discovery(self) -> Mapping[str, Any]:
        return _mapping(self.payload.get("discovery"), "discovery", required=False)

    @property
    def development_stability(self) -> Mapping[str, Any]:
        return _mapping(
            self.payload.get("development_stability"),
            "development_stability",
            required=False,
        )

    @property
    def validation_stability(self) -> Mapping[str, Any]:
        return _mapping(
            self.payload.get("validation_stability"),
            "validation_stability",
            required=False,
        )

    @property
    def validation_ensemble_stability(self) -> Mapping[str, Any]:
        return _mapping(
            self.payload.get("validation_ensemble_stability"),
            "validation_ensemble_stability",
            required=False,
        )

    @property
    def has_stability(self) -> bool:
        return bool(self.development_stability and self.validation_stability)

    def _denominator_entries(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(
            _mapping(value, "candidate denominator entry")
            for value in _sequence(
                self.payload.get("candidate_denominator"), "candidate_denominator"
            )
        )

    def _validate_denominators(self) -> None:
        entries = self._denominator_entries()
        digests = tuple(_text(value.get("feature_digest")).strip() for value in entries)
        if any(not digest for digest in digests) or len(set(digests)) != len(digests):
            raise ResearchReportError(
                "candidate_denominator must contain unique non-empty feature digests"
            )
        denominator = set(digests)
        development = set(_candidate_map(self.development_report))
        validation = set(_candidate_map(self.validation_report))
        if development != denominator:
            raise ResearchReportError(
                "development report denominator differs from candidate_denominator"
            )
        if validation != denominator:
            raise ResearchReportError(
                "validation report denominator differs from candidate_denominator"
            )
        components = _sequence(
            self.frozen_ensemble.get("components"),
            "frozen ensemble components",
        )
        selected = {
            _text(_mapping(value, "ensemble component").get("feature_digest")).strip()
            for value in components
        }
        if not selected or not selected.issubset(denominator):
            raise ResearchReportError(
                "frozen ensemble references candidates outside the denominator"
            )
        if self.development_stability:
            if set(_stability_map(self.development_stability)) != denominator:
                raise ResearchReportError(
                    "development stability denominator differs from candidate_denominator"
                )
        if self.validation_stability:
            if set(_stability_map(self.validation_stability)) != denominator:
                raise ResearchReportError(
                    "validation stability denominator differs from candidate_denominator"
                )

    def candidates(self) -> tuple[CandidateSnapshot, ...]:
        denominator = self._denominator_entries()
        development = _candidate_map(self.development_report)
        validation = _candidate_map(self.validation_report)
        dev_stability = _stability_map(self.development_stability)
        val_stability = _stability_map(self.validation_stability)
        multiplicity = _mapping(
            self.validation_stability.get("multiplicity"),
            "validation multiplicity",
            required=False,
        )
        components = {
            _text(component.get("feature_digest")): component
            for component in (
                _mapping(value, "ensemble component")
                for value in _sequence(
                    self.frozen_ensemble.get("components"),
                    "frozen ensemble components",
                )
            )
        }
        output: list[CandidateSnapshot] = []
        for entry in denominator:
            digest = _text(entry.get("feature_digest"))
            component = components.get(digest, {})
            input_fields = tuple(
                _text(value)
                for value in _sequence(
                    entry.get("input_fields"),
                    "candidate input_fields",
                    required=False,
                )
            )
            output.append(
                CandidateSnapshot(
                    feature_id=_text(entry.get("feature_id")),
                    feature_digest=digest,
                    hypothesis=_text(entry.get("hypothesis")),
                    input_fields=input_fields,
                    lookback=_integer(entry.get("lookback"), 1),
                    generator_id=_text(entry.get("generator_id")),
                    selected=bool(component),
                    weight=_number(component.get("weight")),
                    direction=_integer(component.get("direction"), 0),
                    development=development[digest],
                    validation=validation[digest],
                    development_stability=dev_stability.get(digest, {}),
                    validation_stability=val_stability.get(digest, {}),
                    validation_multiplicity=_mapping(
                        multiplicity.get(digest),
                        "candidate multiplicity",
                        required=False,
                    ),
                )
            )
        return tuple(output)

    def candidate(self, digest: str) -> CandidateSnapshot:
        for candidate in self.candidates():
            if candidate.feature_digest == digest:
                return candidate
        raise KeyError(digest)

    def candidate_rows(self) -> list[dict[str, object]]:
        return [candidate.metric_row() for candidate in self.candidates()]

    def rolling_rows(self, digest: str, split: str) -> list[dict[str, object]]:
        candidate = self.candidate(digest)
        stability = (
            candidate.development_stability
            if split == "development"
            else candidate.validation_stability
        )
        rows = _sequence(
            stability.get("rolling_rank_ic"),
            "rolling_rank_ic",
            required=False,
        )
        return [
            {
                "split": split,
                "start": _text(_mapping(value, "rolling point").get("start")),
                "end": _text(_mapping(value, "rolling point").get("end")),
                "rank_ic": _number(_mapping(value, "rolling point").get("rank_ic")),
                "rank_icir": _number(
                    _mapping(value, "rolling point").get("rank_icir")
                ),
                "periods": _integer(
                    _mapping(value, "rolling point").get("periods")
                ),
            }
            for value in rows
        ]

    def subperiod_rows(self, digest: str, split: str) -> list[dict[str, object]]:
        candidate = self.candidate(digest)
        stability = (
            candidate.development_stability
            if split == "development"
            else candidate.validation_stability
        )
        rows = _sequence(stability.get("subperiods"), "subperiods", required=False)
        return [
            {
                "split": split,
                "period": _text(_mapping(value, "subperiod").get("period")),
                "start": _text(_mapping(value, "subperiod").get("start")),
                "end": _text(_mapping(value, "subperiod").get("end")),
                "rank_ic": _number(_mapping(value, "subperiod").get("rank_ic")),
                "rank_icir": _number(_mapping(value, "subperiod").get("rank_icir")),
                "periods": _integer(_mapping(value, "subperiod").get("periods")),
            }
            for value in rows
        ]

    def quantile_rows(self, digest: str) -> list[dict[str, object]]:
        candidate = self.candidate(digest)
        output: list[dict[str, object]] = []
        for split, report in (
            ("development", candidate.development),
            ("validation", candidate.validation),
        ):
            quantile = _mapping(
                report.get("quantile_diagnostics"),
                f"{split} quantile diagnostics",
                required=False,
            )
            values = _sequence(
                quantile.get("quantile_mean_returns"),
                f"{split} quantile returns",
                required=False,
            )
            for index, value in enumerate(values, start=1):
                output.append(
                    {
                        "split": split,
                        "quantile": f"Q{index}",
                        "mean_return": _number(value),
                    }
                )
        return output

    def correlation_matrix(self, split: str) -> tuple[list[str], list[list[float]]]:
        report = self.development_report if split == "development" else self.validation_report
        correlations = _mapping(
            report.get("factor_value_correlations"),
            f"{split} factor correlations",
            required=False,
        )
        candidates = self.candidates()
        labels = [candidate.feature_id for candidate in candidates]
        digests = [candidate.feature_digest for candidate in candidates]
        matrix = [[0.0 for _ in digests] for _ in digests]
        for row in range(len(digests)):
            matrix[row][row] = 1.0
        index = {digest: position for position, digest in enumerate(digests)}
        for key, value in correlations.items():
            parts = str(key).split("|")
            if len(parts) != 2 or parts[0] not in index or parts[1] not in index:
                continue
            left, right = index[parts[0]], index[parts[1]]
            number = _number(value)
            matrix[left][right] = number
            matrix[right][left] = number
        return labels, matrix

    def universe_rows(self) -> list[dict[str, object]]:
        splits = _mapping(
            self.universe_policy.get("splits"),
            "universe policy splits",
            required=False,
        )
        output: list[dict[str, object]] = []
        for name, raw in splits.items():
            value = _mapping(raw, f"universe split {name}")
            output.append(
                {
                    "split": name,
                    "timestamps": _integer(value.get("timestamps")),
                    "assets": _integer(value.get("assets")),
                    "warmup_timestamps": _integer(value.get("warmup_timestamps")),
                    "first_session_eligible_assets": _integer(
                        value.get("first_session_eligible_assets")
                    ),
                    "eligible_cells": _integer(value.get("eligible_cells")),
                    "average_eligible_assets": _number(
                        value.get("average_eligible_assets")
                    ),
                    "minimum_eligible_assets": _integer(
                        value.get("minimum_eligible_assets")
                    ),
                    "maximum_eligible_assets": _integer(
                        value.get("maximum_eligible_assets")
                    ),
                    "rejected_counts": dict(
                        _mapping(
                            value.get("rejected_counts"),
                            f"universe split {name} rejected_counts",
                            required=False,
                        )
                    ),
                }
            )
        return output

    def discovery_rounds(self) -> list[dict[str, object]]:
        rounds = _sequence(
            self.discovery.get("rounds"),
            "discovery rounds",
            required=False,
        )
        output: list[dict[str, object]] = []
        for raw in rounds:
            value = _mapping(raw, "discovery round")
            selection = _mapping(
                value.get("selection"),
                "discovery round selection",
                required=False,
            )
            components = _sequence(
                selection.get("components"),
                "discovery round components",
                required=False,
            )
            output.append(
                {
                    "round_index": _integer(value.get("round_index")),
                    "new_candidate_digests": list(
                        _sequence(
                            value.get("new_candidate_digests"),
                            "new candidate digests",
                            required=False,
                        )
                    ),
                    "cumulative_candidate_digests": list(
                        _sequence(
                            value.get("cumulative_candidate_digests"),
                            "cumulative candidate digests",
                            required=False,
                        )
                    ),
                    "selected_feature_digests": [
                        _text(_mapping(item, "selection component").get("feature_digest"))
                        for item in components
                    ],
                    "cumulative_report_id": _text(
                        value.get("cumulative_report_id")
                    ),
                    "feedback_id": _text(value.get("feedback_id")),
                }
            )
        return output

    def lineage_rows(self) -> list[dict[str, str]]:
        values = [
            ("schema_version", self.schema_version),
            ("acceptance_id", self.acceptance_id),
            ("data_version", self.data_version),
            (
                "candidate_selection_id",
                _text(self.candidate_universe.get("selection_id")),
            ),
            ("universe_policy_report_id", _text(self.universe_policy.get("report_id"))),
            (
                "development_report_id",
                _text(self.development_report.get("report_id")),
            ),
            ("validation_report_id", _text(self.validation_report.get("report_id"))),
            (
                "development_stability_report_id",
                _text(self.development_stability.get("report_id")),
            ),
            (
                "validation_stability_report_id",
                _text(self.validation_stability.get("report_id")),
            ),
            ("frozen_ensemble_id", _text(self.frozen_ensemble.get("ensemble_id"))),
            ("discovery_id", _text(self.discovery.get("discovery_id"))),
        ]
        return [{"identity": key, "value": value} for key, value in values if value]

    def raw_json(self) -> str:
        return json.dumps(self.payload, indent=2, sort_keys=True, ensure_ascii=False)


def load_research_report(path: str | Path) -> ResearchReportView:
    source = Path(path).expanduser()
    if not source.is_file():
        raise FileNotFoundError(source)
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ResearchReportError("research report root must be a JSON object")
    warnings: list[str] = []
    if not payload.get("development_stability") or not payload.get("validation_stability"):
        warnings.append(
            "legacy report: stability, HAC/bootstrap and multiplicity views are unavailable"
        )
    return ResearchReportView(payload=payload, source=str(source), warnings=tuple(warnings))


def parse_research_report(data: str | bytes, *, source: str = "memory") -> ResearchReportView:
    text = data.decode("utf-8") if isinstance(data, bytes) else data
    payload = json.loads(text)
    if not isinstance(payload, Mapping):
        raise ResearchReportError("research report root must be a JSON object")
    warnings: list[str] = []
    if not payload.get("development_stability") or not payload.get("validation_stability"):
        warnings.append(
            "legacy report: stability, HAC/bootstrap and multiplicity views are unavailable"
        )
    return ResearchReportView(payload=payload, source=source, warnings=tuple(warnings))
