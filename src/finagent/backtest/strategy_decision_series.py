from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, cast


STRATEGY_DECISION_ROW_SCHEMA = "finagent.strategy-decision-row.v1"
STRATEGY_DECISION_MANIFEST_SCHEMA = "finagent.strategy-decision-series.manifest.v1"
STRATEGY_DECISION_QUERY_SCHEMA = "finagent.strategy-decision-series.query.v1"

_PARQUET_COLUMNS = (
    "sequence",
    "row_id",
    "fold_id",
    "session_date",
    "signal_asof",
    "asset",
    "rebalanced",
    "cash_fallback",
    "target_id",
    "alpha_score",
    "alpha_rank",
    "alpha_expected_return",
    "alpha_uncertainty",
    "pre_trade_weight",
    "target_weight",
    "realized_weight",
    "desired_side",
    "desired_quantity",
    "executable_quantity",
    "filled_quantity",
    "reference_price",
    "fill_price",
    "close_price",
    "fees",
    "slippage",
    "gross_pnl",
    "net_pnl",
    "decision_status",
    "client_order_id",
    "constraint_codes_json",
)
_NULLABLE_COLUMNS = (
    "alpha_score",
    "alpha_rank",
    "alpha_expected_return",
    "alpha_uncertainty",
    "pre_trade_weight",
    "target_weight",
    "desired_side",
    "reference_price",
    "fill_price",
    "close_price",
    "decision_status",
    "client_order_id",
)


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=str,
    )


def _digest(prefix: str, value: object, length: int = 64) -> str:
    raw = hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()[:length]
    return f"{prefix}-{raw}"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: object) -> Sequence[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return value
    return ()


def _number(value: object, default: float = 0.0) -> float:
    if value is None:
        return default
    result = float(cast(Any, value))
    if not math.isfinite(result):
        raise ValueError("strategy-decision numeric values must be finite")
    return result


def _integer(value: object, default: int = 0) -> int:
    if value is None:
        return default
    return int(cast(Any, value))


def _optional_number(value: object) -> float | None:
    if value is None or value == "":
        return None
    return _number(value)


def _text(value: object) -> str:
    return "" if value is None else str(value).strip()


def _safe_sibling(name: str, field: str) -> str:
    value = name.strip()
    if not value or Path(value).name != value or value in {".", ".."}:
        raise ValueError(f"{field} must be a sibling filename")
    return value


def _duckdb():
    try:
        import duckdb
    except ImportError as exc:  # pragma: no cover - dependency guidance
        raise RuntimeError(
            "StrategyDecisionSeries Parquet support requires the local-parquet extra"
        ) from exc
    return duckdb


def canonical_execution_ledger_digest(rows: Sequence[Mapping[str, object]]) -> str:
    return _digest("a4-execution-ledger", list(rows), 64)


def _state_quantity(state: Mapping[str, Any], asset: str) -> float:
    position = _mapping(_mapping(state.get("positions")).get(asset))
    return _number(position.get("total_quantity"), 0.0)


def _state_mark(state: Mapping[str, Any], asset: str) -> float | None:
    return _optional_number(_mapping(state.get("marks")).get(asset))


def _state_weight(state: Mapping[str, Any], asset: str) -> float:
    nav = _number(state.get("nav"), 0.0)
    quantity = _state_quantity(state, asset)
    mark = _state_mark(state, asset)
    if nav <= 0.0 or quantity <= 0.0 or mark is None:
        return 0.0
    return quantity * mark / nav


def _fill_asset(fill: Mapping[str, Any]) -> str:
    return _text(fill.get("asset"))


def _fill_quantity(fill: Mapping[str, Any]) -> float:
    return _number(fill.get("quantity"), 0.0)


def _fill_notional(fill: Mapping[str, Any]) -> float:
    if fill.get("notional") is not None:
        return _number(fill.get("notional"))
    return _fill_quantity(fill) * _number(fill.get("execution_price"))


def _fill_fees(fill: Mapping[str, Any]) -> float:
    return _number(_mapping(fill.get("fees")).get("total"), 0.0)


def _asset_pnl(
    previous_state: Mapping[str, Any],
    current_state: Mapping[str, Any],
    fills: Sequence[Mapping[str, Any]],
    asset: str,
) -> float:
    previous_quantity = _state_quantity(previous_state, asset)
    current_quantity = _state_quantity(current_state, asset)
    previous_mark = _state_mark(previous_state, asset)
    current_mark = _state_mark(current_state, asset)
    previous_market_value = (
        previous_quantity * previous_mark
        if previous_quantity > 0.0 and previous_mark is not None
        else 0.0
    )
    current_market_value = (
        current_quantity * current_mark
        if current_quantity > 0.0 and current_mark is not None
        else 0.0
    )
    signed_trade_outflow = 0.0
    fees = 0.0
    for fill in fills:
        if _fill_asset(fill) != asset:
            continue
        side = _text(fill.get("side")).lower()
        notional = _fill_notional(fill)
        if side == "buy":
            signed_trade_outflow += notional
        elif side == "sell":
            signed_trade_outflow -= notional
        else:
            raise ValueError(f"unsupported fill side {side!r}")
        fees += _fill_fees(fill)
    return current_market_value - previous_market_value - signed_trade_outflow - fees


def _weighted_fill_price(
    fills: Sequence[Mapping[str, Any]],
    field: str,
) -> float | None:
    quantity = math.fsum(_fill_quantity(fill) for fill in fills)
    if quantity <= 0.0:
        return None
    total = math.fsum(
        _fill_quantity(fill) * _number(fill.get(field)) for fill in fills
    )
    return total / quantity


def _group_fills(cycle: Mapping[str, Any]) -> dict[str, list[Mapping[str, Any]]]:
    output: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for raw in _sequence(_mapping(cycle.get("execution")).get("fills")):
        fill = _mapping(raw)
        asset = _fill_asset(fill)
        if asset:
            output[asset].append(fill)
    return output


def _decision_map(cycle: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    output: dict[str, Mapping[str, Any]] = {}
    for raw in _sequence(_mapping(cycle.get("compilation")).get("decisions")):
        decision = _mapping(raw)
        asset = _text(_mapping(decision.get("desired")).get("asset"))
        if not asset:
            continue
        if asset in output:
            raise ValueError(f"multiple A3 decisions found for {asset}")
        output[asset] = decision
    return output


@dataclass(frozen=True, slots=True)
class StrategyDecisionRow:
    fold_id: str
    session_date: date
    signal_asof: datetime
    asset: str
    rebalanced: bool
    cash_fallback: bool
    target_id: str
    alpha_score: float | None
    alpha_rank: int | None
    alpha_expected_return: float | None
    alpha_uncertainty: float | None
    pre_trade_weight: float | None
    target_weight: float | None
    realized_weight: float
    desired_side: str | None
    desired_quantity: float
    executable_quantity: int
    filled_quantity: int
    reference_price: float | None
    fill_price: float | None
    close_price: float | None
    fees: float
    slippage: float
    gross_pnl: float
    net_pnl: float
    decision_status: str | None
    client_order_id: str | None
    constraint_codes: tuple[str, ...]
    schema_version: str = STRATEGY_DECISION_ROW_SCHEMA

    def __post_init__(self) -> None:
        if self.signal_asof.tzinfo is None or self.signal_asof.utcoffset() is None:
            raise ValueError("signal_asof must be timezone-aware")
        if not self.fold_id.strip() or not self.asset.strip():
            raise ValueError("fold_id and asset are required")
        optional_values = (
            self.alpha_score,
            self.alpha_expected_return,
            self.alpha_uncertainty,
            self.pre_trade_weight,
            self.target_weight,
            self.reference_price,
            self.fill_price,
            self.close_price,
        )
        if any(value is not None and not math.isfinite(value) for value in optional_values):
            raise ValueError("optional strategy-decision values must be finite")
        required_values = (
            self.realized_weight,
            self.desired_quantity,
            self.fees,
            self.slippage,
            self.gross_pnl,
            self.net_pnl,
        )
        if any(not math.isfinite(value) for value in required_values):
            raise ValueError("strategy-decision values must be finite")
        if self.alpha_rank is not None and self.alpha_rank < 1:
            raise ValueError("alpha_rank must be >= 1")
        if self.executable_quantity < 0 or self.filled_quantity < 0:
            raise ValueError("execution quantities must be non-negative")
        if self.desired_quantity < 0 or self.fees < 0 or self.slippage < 0:
            raise ValueError("desired quantity and costs must be non-negative")
        if self.realized_weight < -1e-12:
            raise ValueError("realized_weight cannot be negative")
        if self.pre_trade_weight is not None and self.pre_trade_weight < -1e-12:
            raise ValueError("pre_trade_weight cannot be negative")
        if self.target_weight is not None and self.target_weight < -1e-12:
            raise ValueError("target_weight cannot be negative")

    @property
    def row_id(self) -> str:
        return _digest("strategy-decision-row", self.to_dict(include_row_id=False), 32)

    def to_dict(self, *, include_row_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "fold_id": self.fold_id,
            "session_date": self.session_date.isoformat(),
            "signal_asof": self.signal_asof.isoformat(),
            "asset": self.asset,
            "rebalanced": self.rebalanced,
            "cash_fallback": self.cash_fallback,
            "target_id": self.target_id,
            "alpha_score": self.alpha_score,
            "alpha_rank": self.alpha_rank,
            "alpha_expected_return": self.alpha_expected_return,
            "alpha_uncertainty": self.alpha_uncertainty,
            "pre_trade_weight": self.pre_trade_weight,
            "target_weight": self.target_weight,
            "realized_weight": self.realized_weight,
            "desired_side": self.desired_side,
            "desired_quantity": self.desired_quantity,
            "executable_quantity": self.executable_quantity,
            "filled_quantity": self.filled_quantity,
            "reference_price": self.reference_price,
            "fill_price": self.fill_price,
            "close_price": self.close_price,
            "fees": self.fees,
            "slippage": self.slippage,
            "gross_pnl": self.gross_pnl,
            "net_pnl": self.net_pnl,
            "decision_status": self.decision_status,
            "client_order_id": self.client_order_id,
            "constraint_codes": list(self.constraint_codes),
        }
        if include_row_id:
            payload["row_id"] = self.row_id
        return payload


AlphaProvider = Callable[[str, datetime], Mapping[str, Mapping[str, object]]]


def materialize_strategy_decision_rows(
    *,
    ledger_rows: Sequence[Mapping[str, object]],
    expected_ledger_digest: str,
    initial_cash: float,
    alpha_provider: AlphaProvider | None = None,
) -> tuple[StrategyDecisionRow, ...]:
    source_rows = tuple(ledger_rows)
    if canonical_execution_ledger_digest(source_rows) != expected_ledger_digest:
        raise ValueError("A4 execution ledger differs from the bound ledger_digest")
    if not math.isfinite(initial_cash) or initial_cash <= 0.0:
        raise ValueError("initial_cash must be positive")

    previous_net: dict[str, Mapping[str, Any]] = {}
    previous_gross: dict[str, Mapping[str, Any]] = {}
    previous_net_nav: dict[str, float] = {}
    previous_gross_nav: dict[str, float] = {}
    output: list[StrategyDecisionRow] = []
    seen_sessions: set[tuple[str, date]] = set()
    initial_state: Mapping[str, Any] = {
        "nav": initial_cash,
        "cash": initial_cash,
        "positions": {},
        "marks": {},
    }

    for raw_row in source_rows:
        ledger_row = _mapping(raw_row)
        fold_id = _text(ledger_row.get("fold_id"))
        point = _mapping(ledger_row.get("point"))
        if not fold_id:
            raise ValueError("A4 ledger row is missing fold_id")
        session_date = date.fromisoformat(_text(point.get("session_date")))
        signal_asof = datetime.fromisoformat(_text(point.get("signal_asof")))
        if signal_asof.tzinfo is None or signal_asof.utcoffset() is None:
            raise ValueError("A4 signal_asof must be timezone-aware")
        session_key = (fold_id, session_date)
        if session_key in seen_sessions:
            raise ValueError(f"duplicate A4 ledger session {session_key!r}")
        seen_sessions.add(session_key)

        target = _mapping(ledger_row.get("target"))
        net_cycle = _mapping(ledger_row.get("net_cycle"))
        gross_cycle = _mapping(ledger_row.get("gross_cycle"))
        current_net = _mapping(ledger_row.get("net_close_state"))
        current_gross = _mapping(ledger_row.get("gross_close_state"))
        close_snapshot = _mapping(ledger_row.get("ex_post_close_snapshot"))
        current_net_nav = _number(current_net.get("nav"))
        current_gross_nav = _number(current_gross.get("nav"))
        if current_net_nav <= 0.0 or current_gross_nav <= 0.0:
            raise ValueError("A4 close-state NAV must remain positive")

        prior_net = previous_net.get(fold_id, initial_state)
        prior_gross = previous_gross.get(fold_id, initial_state)
        prior_net_nav = previous_net_nav.get(fold_id, initial_cash)
        prior_gross_nav = previous_gross_nav.get(fold_id, initial_cash)
        decisions = _decision_map(net_cycle)
        net_fills = _group_fills(net_cycle)
        gross_fills = _group_fills(gross_cycle)
        target_weights = {
            str(key): _number(value)
            for key, value in _mapping(target.get("weights")).items()
        }
        pretrade_state = _mapping(net_cycle.get("state_before")) if net_cycle else {}
        rebalanced = bool(point.get("rebalanced", False))
        alpha = (
            alpha_provider(fold_id, signal_asof)
            if alpha_provider is not None and rebalanced
            else {}
        )

        assets: set[str] = set(alpha)
        assets.update(target_weights)
        for state in (prior_net, current_net, prior_gross, current_gross):
            assets.update(str(key) for key in _mapping(state.get("positions")))
        assets.update(decisions)
        assets.update(net_fills)
        assets.update(gross_fills)

        session_rows: list[StrategyDecisionRow] = []
        execution_rejections = _mapping(
            _mapping(net_cycle.get("execution")).get("rejections")
        )
        close_marks = _mapping(close_snapshot.get("marks"))
        for asset in sorted(assets):
            decision = decisions.get(asset, {})
            desired = _mapping(decision.get("desired"))
            asset_net_fills = net_fills.get(asset, [])
            asset_gross_fills = gross_fills.get(asset, [])
            client_order_id = _text(decision.get("client_order_id")) or None
            constraints = [str(value) for value in _sequence(decision.get("reason_codes"))]
            if client_order_id and client_order_id in execution_rejections:
                constraints.append(str(execution_rejections[client_order_id]))
            alpha_value = _mapping(alpha.get(asset))
            reference_price = _optional_number(desired.get("reference_price"))
            if reference_price is None:
                reference_price = _weighted_fill_price(asset_net_fills, "reference_price")
            session_rows.append(
                StrategyDecisionRow(
                    fold_id=fold_id,
                    session_date=session_date,
                    signal_asof=signal_asof,
                    asset=asset,
                    rebalanced=rebalanced,
                    cash_fallback=bool(point.get("cash_fallback", False)),
                    target_id=_text(point.get("target_id")),
                    alpha_score=_optional_number(alpha_value.get("score")),
                    alpha_rank=(
                        _integer(alpha_value.get("rank"))
                        if alpha_value.get("rank") is not None
                        else None
                    ),
                    alpha_expected_return=_optional_number(
                        alpha_value.get("expected_return")
                    ),
                    alpha_uncertainty=_optional_number(alpha_value.get("uncertainty")),
                    pre_trade_weight=(
                        _state_weight(pretrade_state, asset) if pretrade_state else None
                    ),
                    target_weight=(target_weights.get(asset, 0.0) if target else None),
                    realized_weight=_state_weight(current_net, asset),
                    desired_side=_text(desired.get("side")) or None,
                    desired_quantity=_number(desired.get("requested_quantity"), 0.0),
                    executable_quantity=_integer(
                        decision.get("executable_quantity"), 0
                    ),
                    filled_quantity=int(
                        math.fsum(_fill_quantity(fill) for fill in asset_net_fills)
                    ),
                    reference_price=reference_price,
                    fill_price=_weighted_fill_price(
                        asset_net_fills, "execution_price"
                    ),
                    close_price=_optional_number(close_marks.get(asset)),
                    fees=math.fsum(_fill_fees(fill) for fill in asset_net_fills),
                    slippage=math.fsum(
                        _number(fill.get("slippage"), 0.0) for fill in asset_net_fills
                    ),
                    gross_pnl=_asset_pnl(
                        prior_gross,
                        current_gross,
                        asset_gross_fills,
                        asset,
                    ),
                    net_pnl=_asset_pnl(
                        prior_net,
                        current_net,
                        asset_net_fills,
                        asset,
                    ),
                    decision_status=_text(decision.get("status")) or None,
                    client_order_id=client_order_id,
                    constraint_codes=tuple(dict.fromkeys(constraints)),
                )
            )

        gross_delta = current_gross_nav - prior_gross_nav
        net_delta = current_net_nav - prior_net_nav
        gross_sum = math.fsum(value.gross_pnl for value in session_rows)
        net_sum = math.fsum(value.net_pnl for value in session_rows)
        gross_tolerance = max(1e-6, abs(gross_delta) * 1e-9)
        net_tolerance = max(1e-6, abs(net_delta) * 1e-9)
        if abs(gross_sum - gross_delta) > gross_tolerance:
            raise ValueError(
                "asset gross PnL does not reconcile to A4 gross NAV change: "
                f"{gross_sum} != {gross_delta}"
            )
        if abs(net_sum - net_delta) > net_tolerance:
            raise ValueError(
                "asset net PnL does not reconcile to A4 net NAV change: "
                f"{net_sum} != {net_delta}"
            )

        output.extend(session_rows)
        previous_net[fold_id] = current_net
        previous_gross[fold_id] = current_gross
        previous_net_nav[fold_id] = current_net_nav
        previous_gross_nav[fold_id] = current_gross_nav

    ordered = tuple(
        sorted(output, key=lambda value: (value.session_date, value.fold_id, value.asset))
    )
    keys = [(value.fold_id, value.session_date, value.asset) for value in ordered]
    if len(keys) != len(set(keys)):
        raise ValueError("StrategyDecisionSeries row identity is not unique")
    return ordered


def _series_identity_payload(
    *,
    portfolio_validation_id: str,
    a4_spec_id: str,
    source_program_result_id: str,
    source_program_report_digest: str,
    source_selection_id: str,
    data_version: str,
    execution_ledger_digest: str,
    selected_feature_digests: Sequence[str],
    alpha_model_ids: Sequence[str],
    rows_digest: str,
) -> dict[str, object]:
    return {
        "schema_version": STRATEGY_DECISION_MANIFEST_SCHEMA,
        "row_schema_version": STRATEGY_DECISION_ROW_SCHEMA,
        "portfolio_validation_id": portfolio_validation_id,
        "a4_spec_id": a4_spec_id,
        "source_program_result_id": source_program_result_id,
        "source_program_report_digest": source_program_report_digest,
        "source_selection_id": source_selection_id,
        "data_version": data_version,
        "execution_ledger_digest": execution_ledger_digest,
        "selected_feature_digests": list(selected_feature_digests),
        "alpha_model_ids": list(alpha_model_ids),
        "rows_digest": rows_digest,
    }


@dataclass(frozen=True, slots=True)
class StrategyDecisionSeriesManifest:
    series_id: str
    portfolio_validation_id: str
    a4_spec_id: str
    source_program_result_id: str
    source_program_spec_id: str
    source_program_report_digest: str
    source_selection_id: str
    data_version: str
    execution_ledger_digest: str
    selected_feature_digests: tuple[str, ...]
    alpha_model_ids: tuple[str, ...]
    rows_digest: str
    source_report_file: str
    source_report_sha256: str
    source_ledger_file: str
    source_ledger_sha256: str
    data_file: str
    data_sha256: str
    row_count: int
    source_session_count: int
    row_session_count: int
    asset_count: int
    start_date: str | None
    end_date: str | None
    columns: tuple[str, ...] = _PARQUET_COLUMNS
    nullable_columns: tuple[str, ...] = _NULLABLE_COLUMNS
    authority: str = "authoritative"
    schema_version: str = STRATEGY_DECISION_MANIFEST_SCHEMA

    def __post_init__(self) -> None:
        required = (
            self.series_id,
            self.portfolio_validation_id,
            self.a4_spec_id,
            self.source_program_result_id,
            self.source_program_spec_id,
            self.source_program_report_digest,
            self.source_selection_id,
            self.data_version,
            self.execution_ledger_digest,
            self.rows_digest,
            self.source_report_sha256,
            self.source_ledger_sha256,
            self.data_sha256,
        )
        if any(not value.strip() for value in required):
            raise ValueError("StrategyDecisionSeries manifest identities are required")
        if self.authority != "authoritative":
            raise ValueError("StrategyDecisionSeries manifest must be authoritative")
        if min(
            self.row_count,
            self.source_session_count,
            self.row_session_count,
            self.asset_count,
        ) < 0:
            raise ValueError("StrategyDecisionSeries manifest counts cannot be negative")
        if self.columns != _PARQUET_COLUMNS:
            raise ValueError("StrategyDecisionSeries manifest columns are not canonical")
        expected_series_id = _digest(
            "strategy-decision-series",
            _series_identity_payload(
                portfolio_validation_id=self.portfolio_validation_id,
                a4_spec_id=self.a4_spec_id,
                source_program_result_id=self.source_program_result_id,
                source_program_report_digest=self.source_program_report_digest,
                source_selection_id=self.source_selection_id,
                data_version=self.data_version,
                execution_ledger_digest=self.execution_ledger_digest,
                selected_feature_digests=self.selected_feature_digests,
                alpha_model_ids=self.alpha_model_ids,
                rows_digest=self.rows_digest,
            ),
            40,
        )
        if self.series_id != expected_series_id:
            raise ValueError("StrategyDecisionSeries series_id differs from manifest content")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "authority": self.authority,
            "series_id": self.series_id,
            "portfolio_validation_id": self.portfolio_validation_id,
            "a4_spec_id": self.a4_spec_id,
            "source_program_result_id": self.source_program_result_id,
            "source_program_spec_id": self.source_program_spec_id,
            "source_program_report_digest": self.source_program_report_digest,
            "source_selection_id": self.source_selection_id,
            "data_version": self.data_version,
            "execution_ledger_digest": self.execution_ledger_digest,
            "selected_feature_digests": list(self.selected_feature_digests),
            "alpha_model_ids": list(self.alpha_model_ids),
            "rows_digest": self.rows_digest,
            "source_report_file": self.source_report_file,
            "source_report_sha256": self.source_report_sha256,
            "source_ledger_file": self.source_ledger_file,
            "source_ledger_sha256": self.source_ledger_sha256,
            "data_file": self.data_file,
            "data_sha256": self.data_sha256,
            "row_count": self.row_count,
            "source_session_count": self.source_session_count,
            "row_session_count": self.row_session_count,
            "asset_count": self.asset_count,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "columns": list(self.columns),
            "nullable_columns": list(self.nullable_columns),
            "alpha_score_definition": (
                "frozen weighted/directed cross-sectional z-score reconstructed from "
                "the exact A4 AlphaModel forecast and train-only calibration"
            ),
            "pnl_definition": (
                "asset wealth contribution = close market value - prior close market "
                "value - signed executed notional - actual fees; slippage is embedded "
                "in net execution price and also persisted separately"
            ),
            "ordering": (
                "session_date, fold_id, asset; sequence is deterministic 0-based order"
            ),
            "scope": (
                "historical A4 strategy-decision evidence only; no reserve, promotion, "
                "PAPER, realtime or live-capital authority"
            ),
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, object]) -> StrategyDecisionSeriesManifest:
        if raw.get("schema_version") != STRATEGY_DECISION_MANIFEST_SCHEMA:
            raise ValueError("unsupported StrategyDecisionSeries manifest schema")
        return cls(
            series_id=_text(raw.get("series_id")),
            portfolio_validation_id=_text(raw.get("portfolio_validation_id")),
            a4_spec_id=_text(raw.get("a4_spec_id")),
            source_program_result_id=_text(raw.get("source_program_result_id")),
            source_program_spec_id=_text(raw.get("source_program_spec_id")),
            source_program_report_digest=_text(raw.get("source_program_report_digest")),
            source_selection_id=_text(raw.get("source_selection_id")),
            data_version=_text(raw.get("data_version")),
            execution_ledger_digest=_text(raw.get("execution_ledger_digest")),
            selected_feature_digests=tuple(
                str(value) for value in _sequence(raw.get("selected_feature_digests"))
            ),
            alpha_model_ids=tuple(
                str(value) for value in _sequence(raw.get("alpha_model_ids"))
            ),
            rows_digest=_text(raw.get("rows_digest")),
            source_report_file=_safe_sibling(
                _text(raw.get("source_report_file")), "source_report_file"
            ),
            source_report_sha256=_text(raw.get("source_report_sha256")),
            source_ledger_file=_safe_sibling(
                _text(raw.get("source_ledger_file")), "source_ledger_file"
            ),
            source_ledger_sha256=_text(raw.get("source_ledger_sha256")),
            data_file=_safe_sibling(_text(raw.get("data_file")), "data_file"),
            data_sha256=_text(raw.get("data_sha256")),
            row_count=_integer(raw.get("row_count")),
            source_session_count=_integer(raw.get("source_session_count")),
            row_session_count=_integer(raw.get("row_session_count")),
            asset_count=_integer(raw.get("asset_count")),
            start_date=_text(raw.get("start_date")) or None,
            end_date=_text(raw.get("end_date")) or None,
            columns=tuple(str(value) for value in _sequence(raw.get("columns"))),
            nullable_columns=tuple(
                str(value) for value in _sequence(raw.get("nullable_columns"))
            ),
            authority=_text(raw.get("authority")),
        )

    @classmethod
    def read_json(cls, path: str | Path) -> StrategyDecisionSeriesManifest:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(value, Mapping):
            raise ValueError("StrategyDecisionSeries manifest root must be an object")
        return cls.from_dict(value)


def _create_parquet(path: Path, rows: Sequence[StrategyDecisionRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".parquet", dir=str(path.parent)
    )
    os.close(fd)
    temp = Path(temp_name)
    temp.unlink(missing_ok=True)
    duckdb = _duckdb()
    connection = duckdb.connect()
    try:
        connection.execute(
            """
            CREATE TABLE decisions (
                sequence BIGINT NOT NULL,
                row_id VARCHAR NOT NULL,
                fold_id VARCHAR NOT NULL,
                session_date DATE NOT NULL,
                signal_asof VARCHAR NOT NULL,
                asset VARCHAR NOT NULL,
                rebalanced BOOLEAN NOT NULL,
                cash_fallback BOOLEAN NOT NULL,
                target_id VARCHAR NOT NULL,
                alpha_score DOUBLE,
                alpha_rank BIGINT,
                alpha_expected_return DOUBLE,
                alpha_uncertainty DOUBLE,
                pre_trade_weight DOUBLE,
                target_weight DOUBLE,
                realized_weight DOUBLE NOT NULL,
                desired_side VARCHAR,
                desired_quantity DOUBLE NOT NULL,
                executable_quantity BIGINT NOT NULL,
                filled_quantity BIGINT NOT NULL,
                reference_price DOUBLE,
                fill_price DOUBLE,
                close_price DOUBLE,
                fees DOUBLE NOT NULL,
                slippage DOUBLE NOT NULL,
                gross_pnl DOUBLE NOT NULL,
                net_pnl DOUBLE NOT NULL,
                decision_status VARCHAR,
                client_order_id VARCHAR,
                constraint_codes_json VARCHAR NOT NULL
            )
            """
        )
        values = [
            (
                index,
                row.row_id,
                row.fold_id,
                row.session_date,
                row.signal_asof.isoformat(),
                row.asset,
                row.rebalanced,
                row.cash_fallback,
                row.target_id,
                row.alpha_score,
                row.alpha_rank,
                row.alpha_expected_return,
                row.alpha_uncertainty,
                row.pre_trade_weight,
                row.target_weight,
                row.realized_weight,
                row.desired_side,
                row.desired_quantity,
                row.executable_quantity,
                row.filled_quantity,
                row.reference_price,
                row.fill_price,
                row.close_price,
                row.fees,
                row.slippage,
                row.gross_pnl,
                row.net_pnl,
                row.decision_status,
                row.client_order_id,
                _canonical_json(list(row.constraint_codes)),
            )
            for index, row in enumerate(rows)
        ]
        if values:
            placeholders = ",".join("?" for _ in _PARQUET_COLUMNS)
            connection.executemany(
                f"INSERT INTO decisions VALUES ({placeholders})", values
            )
        target = str(temp).replace("'", "''")
        connection.execute(
            f"COPY decisions TO '{target}' (FORMAT PARQUET, COMPRESSION ZSTD)"
        )
    finally:
        connection.close()
    temp.replace(path)


def _read_jsonl(path: Path) -> tuple[Mapping[str, object], ...]:
    output: list[Mapping[str, object]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, 1):
            if not raw.strip():
                continue
            value = json.loads(raw)
            if not isinstance(value, Mapping):
                raise ValueError(f"{path}:{line_number}: JSONL row must be an object")
            output.append(value)
    return tuple(output)


def write_strategy_decision_series(
    *,
    a4_report: Mapping[str, object],
    rows: Sequence[StrategyDecisionRow],
    source_report_path: str | Path,
    source_ledger_path: str | Path,
    manifest_path: str | Path,
    data_path: str | Path,
) -> StrategyDecisionSeriesManifest:
    source_report = Path(source_report_path).resolve()
    source_ledger = Path(source_ledger_path).resolve()
    manifest_target = Path(manifest_path).resolve()
    data_target = Path(data_path).resolve()
    if len(
        {
            source_report.parent,
            source_ledger.parent,
            manifest_target.parent,
            data_target.parent,
        }
    ) != 1:
        raise ValueError(
            "V4-0 source report, source ledger, manifest and Parquet must be sibling files"
        )
    if not source_report.is_file() or not source_ledger.is_file():
        raise FileNotFoundError("V4-0 requires the immutable A4 report and ledger files")
    if a4_report.get("schema_version") != "finagent.ashare-portfolio-validation.v1":
        raise ValueError("StrategyDecisionSeries requires an A4 validation report")
    physical_report = json.loads(source_report.read_text(encoding="utf-8"))
    if _canonical_json(physical_report) != _canonical_json(a4_report):
        raise ValueError("provided A4 report mapping differs from source report file")

    spec = _mapping(a4_report.get("validation_spec"))
    validation = _mapping(spec.get("validation_config"))
    if _number(validation.get("initial_cash"), 0.0) <= 0.0:
        raise ValueError("A4 report validation_config.initial_cash is invalid")
    portfolio_validation_id = _text(a4_report.get("portfolio_validation_id"))
    ledger_digest = _text(a4_report.get("ledger_digest"))
    if not portfolio_validation_id or not ledger_digest:
        raise ValueError("A4 report is missing portfolio_validation_id or ledger_digest")
    source_rows = _read_jsonl(source_ledger)
    if canonical_execution_ledger_digest(source_rows) != ledger_digest:
        raise ValueError("source A4 ledger bytes do not match report ledger_digest")

    ordered = tuple(
        sorted(rows, key=lambda value: (value.session_date, value.fold_id, value.asset))
    )
    rows_digest = _digest(
        "strategy-decision-rows",
        [value.to_dict() for value in ordered],
        64,
    )
    selected_feature_digests = tuple(
        str(value) for value in _sequence(spec.get("selected_feature_digests"))
    )
    alpha_model_ids = tuple(
        sorted(
            {
                _text(_mapping(value).get("alpha_model_id"))
                for value in _sequence(a4_report.get("folds"))
                if _text(_mapping(value).get("alpha_model_id"))
            }
        )
    )
    identity_payload = _series_identity_payload(
        portfolio_validation_id=portfolio_validation_id,
        a4_spec_id=_text(spec.get("spec_id")),
        source_program_result_id=_text(spec.get("source_program_result_id")),
        source_program_report_digest=_text(spec.get("source_report_digest")),
        source_selection_id=_text(spec.get("source_selection_id")),
        data_version=_text(spec.get("data_version")),
        execution_ledger_digest=ledger_digest,
        selected_feature_digests=selected_feature_digests,
        alpha_model_ids=alpha_model_ids,
        rows_digest=rows_digest,
    )
    series_id = _digest("strategy-decision-series", identity_payload, 40)
    _create_parquet(data_target, ordered)
    dates = [value.session_date for value in ordered]
    source_sessions = {
        _text(_mapping(value.get("point")).get("session_date")) for value in source_rows
    }
    source_sessions.discard("")
    manifest = StrategyDecisionSeriesManifest(
        series_id=series_id,
        portfolio_validation_id=portfolio_validation_id,
        a4_spec_id=_text(spec.get("spec_id")),
        source_program_result_id=_text(spec.get("source_program_result_id")),
        source_program_spec_id=_text(spec.get("source_program_spec_id")),
        source_program_report_digest=_text(spec.get("source_report_digest")),
        source_selection_id=_text(spec.get("source_selection_id")),
        data_version=_text(spec.get("data_version")),
        execution_ledger_digest=ledger_digest,
        selected_feature_digests=selected_feature_digests,
        alpha_model_ids=alpha_model_ids,
        rows_digest=rows_digest,
        source_report_file=source_report.name,
        source_report_sha256=_sha256(source_report),
        source_ledger_file=source_ledger.name,
        source_ledger_sha256=_sha256(source_ledger),
        data_file=data_target.name,
        data_sha256=_sha256(data_target),
        row_count=len(ordered),
        source_session_count=len(source_sessions),
        row_session_count=len({value.session_date for value in ordered}),
        asset_count=len({value.asset for value in ordered}),
        start_date=min(dates).isoformat() if dates else None,
        end_date=max(dates).isoformat() if dates else None,
    )
    manifest_target.write_text(
        json.dumps(manifest.to_dict(), indent=2, sort_keys=True, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    return manifest


class StrategyDecisionSeriesProjection:
    """Verified bounded read projection over immutable V4-0 Parquet evidence."""

    def __init__(self, manifest_path: str | Path) -> None:
        self.manifest_path = Path(manifest_path).resolve()
        self.manifest = StrategyDecisionSeriesManifest.read_json(self.manifest_path)
        root = self.manifest_path.parent
        self.report_path = root / self.manifest.source_report_file
        self.ledger_path = root / self.manifest.source_ledger_file
        self.data_path = root / self.manifest.data_file
        for path in (self.report_path, self.ledger_path, self.data_path):
            if path.parent.resolve() != root:
                raise ValueError("V4-0 manifest sibling escaped its evidence root")
            if not path.is_file():
                raise FileNotFoundError(path)
        if _sha256(self.report_path) != self.manifest.source_report_sha256:
            raise ValueError("V4-0 source A4 report SHA-256 mismatch")
        if _sha256(self.ledger_path) != self.manifest.source_ledger_sha256:
            raise ValueError("V4-0 source A4 ledger SHA-256 mismatch")
        if _sha256(self.data_path) != self.manifest.data_sha256:
            raise ValueError("V4-0 Parquet SHA-256 mismatch")

        report = json.loads(self.report_path.read_text(encoding="utf-8"))
        if not isinstance(report, Mapping):
            raise ValueError("V4-0 source A4 report root must be an object")
        spec = _mapping(report.get("validation_spec"))
        checks = {
            "portfolio_validation_id": report.get("portfolio_validation_id"),
            "a4_spec_id": spec.get("spec_id"),
            "source_program_result_id": spec.get("source_program_result_id"),
            "source_program_spec_id": spec.get("source_program_spec_id"),
            "source_program_report_digest": spec.get("source_report_digest"),
            "source_selection_id": spec.get("source_selection_id"),
            "data_version": spec.get("data_version"),
            "execution_ledger_digest": report.get("ledger_digest"),
        }
        for field, actual in checks.items():
            if _text(actual) != _text(getattr(self.manifest, field)):
                raise ValueError(f"V4-0 manifest binding mismatch: {field}")
        selected = tuple(
            str(value) for value in _sequence(spec.get("selected_feature_digests"))
        )
        if selected != self.manifest.selected_feature_digests:
            raise ValueError("V4-0 selected factor identity mismatch")
        alpha_model_ids = tuple(
            sorted(
                {
                    _text(_mapping(value).get("alpha_model_id"))
                    for value in _sequence(report.get("folds"))
                    if _text(_mapping(value).get("alpha_model_id"))
                }
            )
        )
        if alpha_model_ids != self.manifest.alpha_model_ids:
            raise ValueError("V4-0 alpha-model identity mismatch")
        source_rows = _read_jsonl(self.ledger_path)
        if (
            canonical_execution_ledger_digest(source_rows)
            != self.manifest.execution_ledger_digest
        ):
            raise ValueError("V4-0 source ledger canonical digest mismatch")
        self._validate_parquet()

    def _validate_parquet(self) -> None:
        duckdb = _duckdb()
        connection = duckdb.connect()
        try:
            columns = tuple(
                str(row[0])
                for row in connection.execute(
                    "DESCRIBE SELECT * FROM read_parquet(?)",
                    (str(self.data_path),),
                ).fetchall()
            )
            if columns != self.manifest.columns:
                raise ValueError(
                    f"V4-0 Parquet columns differ: {columns!r} != {self.manifest.columns!r}"
                )
            summary = connection.execute(
                """
                SELECT count(*), count(DISTINCT sequence), count(DISTINCT row_id),
                       min(sequence), max(sequence)
                FROM read_parquet(?)
                """,
                (str(self.data_path),),
            ).fetchone()
            count = _integer(summary[0])
            if count != self.manifest.row_count:
                raise ValueError("V4-0 Parquet row count differs from manifest")
            if _integer(summary[1]) != count or _integer(summary[2]) != count:
                raise ValueError("V4-0 Parquet sequence/row identity is not unique")
            if count and (
                _integer(summary[3]) != 0 or _integer(summary[4]) != count - 1
            ):
                raise ValueError("V4-0 Parquet sequence is not contiguous")
        finally:
            connection.close()

    def query(
        self,
        *,
        asset: str | None = None,
        start: date | None = None,
        end: date | None = None,
        fold_id: str | None = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> dict[str, object]:
        if not 1 <= limit <= 5000:
            raise ValueError("limit must be in [1, 5000]")
        if offset < 0:
            raise ValueError("offset must be >= 0")
        if start is not None and end is not None and end < start:
            raise ValueError("end cannot be before start")
        where: list[str] = []
        parameters: list[object] = [str(self.data_path)]
        if asset:
            where.append("asset = ?")
            parameters.append(asset.strip())
        if fold_id:
            where.append("fold_id = ?")
            parameters.append(fold_id.strip())
        if start is not None:
            where.append("session_date >= ?")
            parameters.append(start)
        if end is not None:
            where.append("session_date <= ?")
            parameters.append(end)
        predicate = f" WHERE {' AND '.join(where)}" if where else ""
        duckdb = _duckdb()
        connection = duckdb.connect()
        try:
            total_row = connection.execute(
                f"SELECT count(*) FROM read_parquet(?) {predicate}",
                parameters,
            ).fetchone()
            total = _integer(total_row[0])
            values = connection.execute(
                f"SELECT * FROM read_parquet(?) {predicate} "
                "ORDER BY sequence LIMIT ? OFFSET ?",
                [*parameters, limit, offset],
            )
            names = [str(value[0]) for value in values.description]
            items: list[dict[str, object]] = []
            for raw in values.fetchall():
                row = dict(zip(names, raw, strict=True))
                row["session_date"] = cast(date, row["session_date"]).isoformat()
                row["signal_asof"] = str(row["signal_asof"])
                row["constraint_codes"] = json.loads(
                    str(row.pop("constraint_codes_json"))
                )
                items.append(row)
        finally:
            connection.close()
        return {
            "schema_version": STRATEGY_DECISION_QUERY_SCHEMA,
            "read_only": True,
            "authority": "authoritative",
            "series_id": self.manifest.series_id,
            "portfolio_validation_id": self.manifest.portfolio_validation_id,
            "filters": {
                "asset": asset,
                "start": start.isoformat() if start else None,
                "end": end.isoformat() if end else None,
                "fold_id": fold_id,
                "limit": limit,
                "offset": offset,
            },
            "total": total,
            "items": items,
        }
