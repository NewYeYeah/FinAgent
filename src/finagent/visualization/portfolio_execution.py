from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from .strategy_explorer import StrategyDecisionExplorerProjection
from .workspace_v2 import WorkspaceV2Projection


PORTFOLIO_EXECUTION_CATALOG_SCHEMA = "finagent.portfolio-execution.catalog.v1"
PORTFOLIO_EXECUTION_DETAIL_SCHEMA = "finagent.portfolio-execution.detail.v1"
PORTFOLIO_EXECUTION_SERIES_SCHEMA = "finagent.portfolio-execution.series.v1"
PORTFOLIO_EXECUTION_ANALYTICS_SCHEMA = "finagent.portfolio-execution.analytics.v1"


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: object) -> Sequence[Any]:
    return (
        value
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))
        else ()
    )


def _text(value: object) -> str:
    return "" if value is None else str(value).strip()


def _number(value: object) -> float:
    result = float(value)  # type: ignore[arg-type]
    if not math.isfinite(result):
        raise ValueError("V4-4 numeric source value must be finite")
    return result


def _in_range(
    value: str,
    *,
    start: date | None,
    end: date | None,
) -> bool:
    if start is not None and value < start.isoformat():
        return False
    if end is not None and value > end.isoformat():
        return False
    return True


def _validate_range(start: date | None, end: date | None) -> None:
    if start is not None and end is not None and start > end:
        raise ValueError("V4-4 start date must not be after end date")


@dataclass(frozen=True, slots=True)
class PortfolioExecutionItem:
    portfolio_validation_id: str
    strategy_series_id: str
    source_program_result_id: str
    source_selection_id: str
    row_count: int
    asset_count: int
    fold_count: int
    session_count: int
    start_date: str | None
    end_date: str | None
    status: str

    def to_dict(self) -> dict[str, object]:
        return {
            "portfolio_validation_id": self.portfolio_validation_id,
            "strategy_series_id": self.strategy_series_id,
            "source_program_result_id": self.source_program_result_id,
            "source_selection_id": self.source_selection_id,
            "row_count": self.row_count,
            "asset_count": self.asset_count,
            "fold_count": self.fold_count,
            "session_count": self.session_count,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "status": self.status,
            "authority": "authoritative_identity_binding",
            "detail_url": (
                f"/api/v4/portfolio-execution/{self.portfolio_validation_id}"
            ),
        }


class PortfolioExecutionInteractiveProjection:
    """V4-4 linked analytical projection over authoritative A4 and V4-0 evidence.

    A4 portfolio points and frozen aggregate metrics remain the portfolio authority.
    V4-0 StrategyDecisionSeries rows remain the asset/order/weight/PnL authority.
    Drawdown, rolling views, monthly matrices and filtered aggregations are explicit
    deterministic server-side presentation derivatives. React is not a calculation
    authority for financial or statistical facts.
    """

    def __init__(
        self,
        workspace_v2: WorkspaceV2Projection,
        strategy_explorer: StrategyDecisionExplorerProjection,
    ) -> None:
        self.workspace_v2 = workspace_v2
        self.strategy_explorer = strategy_explorer
        self._items: dict[str, PortfolioExecutionItem] = {}
        self._warnings: list[str] = []
        self._scan()

    @property
    def warnings(self) -> tuple[str, ...]:
        return tuple(self._warnings)

    def _scan(self) -> None:
        items: dict[str, PortfolioExecutionItem] = {}
        warnings: list[str] = []
        catalog = self.strategy_explorer.catalog()
        for raw in _sequence(catalog.get("items")):
            source = _mapping(raw)
            validation_id = _text(source.get("portfolio_validation_id"))
            series_id = _text(source.get("series_id"))
            if not validation_id or not series_id:
                continue
            try:
                resolved = self.strategy_explorer.by_portfolio(validation_id)
                if resolved.series_id != series_id:
                    raise ValueError(
                        "V4-4 portfolio resolves to a different StrategyDecisionSeries"
                    )
                dimensions = self.strategy_explorer.dimensions(series_id)
                portfolio = self.workspace_v2.portfolio_cockpit(validation_id)
            except (KeyError, RuntimeError, ValueError, TypeError) as exc:
                warnings.append(
                    f"{validation_id}: {type(exc).__name__}: {exc}"
                )
                continue
            if portfolio.get("no_portfolio") is True:
                warnings.append(
                    f"{validation_id}: authoritative A4 portfolio aggregate is unavailable"
                )
                continue
            item = PortfolioExecutionItem(
                portfolio_validation_id=validation_id,
                strategy_series_id=series_id,
                source_program_result_id=_text(source.get("source_program_result_id")),
                source_selection_id=_text(source.get("source_selection_id")),
                row_count=int(source.get("row_count", 0)),
                asset_count=len(_sequence(dimensions.get("assets"))),
                fold_count=len(_sequence(dimensions.get("folds"))),
                session_count=int(dimensions.get("session_count", 0)),
                start_date=(
                    _text(dimensions.get("start_date")) or None
                ),
                end_date=_text(dimensions.get("end_date")) or None,
                status=_text(portfolio.get("status")),
            )
            if validation_id in items and items[validation_id] != item:
                warnings.append(
                    f"{validation_id}: conflicting V4-4 identity binding; omitted"
                )
                items.pop(validation_id, None)
                continue
            items[validation_id] = item
        self._items = items
        self._warnings = warnings

    def status(self) -> dict[str, object]:
        return {
            "schema_version": "finagent.portfolio-execution.status.v1",
            "read_only": True,
            "item_count": len(self._items),
            "warning_count": len(self._warnings),
            "portfolio_authority": "authoritative_a4_report",
            "decision_authority": "authoritative_v4_0_strategy_decision_rows",
            "browser_recomputation": False,
            "benchmark_available": False,
            "order_id_available": False,
        }

    def catalog(self) -> dict[str, object]:
        return {
            "schema_version": PORTFOLIO_EXECUTION_CATALOG_SCHEMA,
            "read_only": True,
            "items": [self._items[key].to_dict() for key in sorted(self._items)],
            "warnings": list(self._warnings),
        }

    def item(self, validation_id: str) -> PortfolioExecutionItem:
        try:
            return self._items[validation_id]
        except KeyError as exc:
            raise KeyError(validation_id) from exc

    def detail(self, validation_id: str) -> dict[str, object]:
        item = self.item(validation_id)
        portfolio = self.workspace_v2.portfolio_cockpit(validation_id)
        execution = self.workspace_v2.execution_cockpit(validation_id)
        metrics = dict(_mapping(portfolio.get("metrics")))
        economic = dict(_mapping(portfolio.get("economic_evidence")))
        folds = [dict(_mapping(value)) for value in _sequence(portfolio.get("folds"))]
        ledger = dict(_mapping(execution.get("ledger")))
        return {
            "schema_version": PORTFOLIO_EXECUTION_DETAIL_SCHEMA,
            "read_only": True,
            "item": item.to_dict(),
            "portfolio_metrics": metrics,
            "economic_evidence": economic,
            "folds": folds,
            "ledger": ledger,
            "authority": {
                "portfolio_metrics": "authoritative_a4_report",
                "economic_evidence": "authoritative_a4_report",
                "folds": "authoritative_a4_report",
                "ledger": "authoritative_a4_execution_ledger",
            },
            "presentation": {
                "browser_recomputation": False,
                "drawdown": "derived_presentation_from_authoritative_a4_nav",
                "rolling": "derived_presentation_from_authoritative_a4_returns",
                "monthly_returns": (
                    "derived_presentation_from_authoritative_a4_returns"
                ),
                "filtered_costs": (
                    "derived_presentation_sum_of_authoritative_v4_0_cost_rows"
                ),
                "constraint_counts": (
                    "derived_presentation_count_of_authoritative_v4_0_reason_codes"
                ),
                "target_realized": "authoritative_v4_0_rows",
                "benchmark_available": False,
                "order_id_available": False,
                "benchmark_note": (
                    "No immutable benchmark return/NAV evidence is persisted for V4-4"
                ),
                "order_identity_note": (
                    "V4-0 persists asset/session order quantities and reason codes but not "
                    "a durable order_id identity; V4-4 does not invent one"
                ),
            },
        }

    def _portfolio_points(
        self,
        validation_id: str,
        *,
        start: date | None,
        end: date | None,
        fold_id: str | None,
    ) -> list[dict[str, object]]:
        _validate_range(start, end)
        portfolio = self.workspace_v2.portfolio_cockpit(validation_id)
        output: list[dict[str, object]] = []
        for raw in _sequence(portfolio.get("nav_series")):
            point = _mapping(raw)
            session_date = _text(point.get("session_date"))
            if not _in_range(session_date, start=start, end=end):
                continue
            if fold_id and _text(point.get("fold_id")) != fold_id:
                continue
            output.append(
                {
                    "session_date": session_date,
                    "fold_id": _text(point.get("fold_id")),
                    "net_nav": _number(point.get("net_nav")),
                    "gross_nav": _number(point.get("gross_nav")),
                    "net_return": _number(point.get("net_return")),
                    "gross_return": _number(point.get("gross_return")),
                    "authority": "authoritative_a4_point",
                }
            )
        return output

    def portfolio_series(
        self,
        validation_id: str,
        *,
        start: date | None = None,
        end: date | None = None,
        fold_id: str | None = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> dict[str, object]:
        self.item(validation_id)
        points = self._portfolio_points(
            validation_id,
            start=start,
            end=end,
            fold_id=fold_id,
        )
        total = len(points)
        return {
            "schema_version": PORTFOLIO_EXECUTION_SERIES_SCHEMA,
            "read_only": True,
            "authority": "authoritative_a4_points",
            "portfolio_validation_id": validation_id,
            "total": total,
            "offset": offset,
            "limit": limit,
            "items": points[offset : offset + limit],
        }

    def _strategy_series_id(self, validation_id: str) -> str:
        return self.item(validation_id).strategy_series_id

    def decisions(
        self,
        validation_id: str,
        *,
        asset: str | None = None,
        session_date: date | None = None,
        start: date | None = None,
        end: date | None = None,
        fold_id: str | None = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> dict[str, object]:
        if session_date is not None:
            if start is not None or end is not None:
                raise ValueError(
                    "V4-4 session_date cannot be combined with start/end"
                )
            start = session_date
            end = session_date
        _validate_range(start, end)
        return self.strategy_explorer.query(
            self._strategy_series_id(validation_id),
            asset=asset,
            start=start,
            end=end,
            fold_id=fold_id,
            limit=limit,
            offset=offset,
        )

    def _iter_decisions(
        self,
        validation_id: str,
        *,
        asset: str | None,
        start: date | None,
        end: date | None,
        fold_id: str | None,
    ) -> Iterator[Mapping[str, Any]]:
        offset = 0
        while True:
            page = self.decisions(
                validation_id,
                asset=asset,
                start=start,
                end=end,
                fold_id=fold_id,
                limit=5000,
                offset=offset,
            )
            items = [_mapping(value) for value in _sequence(page.get("items"))]
            yield from items
            offset += len(items)
            total = int(page.get("total", 0))
            if not items or offset >= total:
                break

    @staticmethod
    def _drawdown(points: Sequence[Mapping[str, Any]]) -> list[dict[str, object]]:
        net_peak = 0.0
        gross_peak = 0.0
        output: list[dict[str, object]] = []
        for point in points:
            net_nav = _number(point.get("net_nav"))
            gross_nav = _number(point.get("gross_nav"))
            net_peak = max(net_peak, net_nav)
            gross_peak = max(gross_peak, gross_nav)
            output.append(
                {
                    "session_date": _text(point.get("session_date")),
                    "fold_id": _text(point.get("fold_id")),
                    "net_drawdown": net_nav / net_peak - 1.0 if net_peak > 0 else 0.0,
                    "gross_drawdown": (
                        gross_nav / gross_peak - 1.0 if gross_peak > 0 else 0.0
                    ),
                }
            )
        return output

    @staticmethod
    def _rolling(
        points: Sequence[Mapping[str, Any]],
        *,
        annualization: float,
        window: int,
    ) -> list[dict[str, object]]:
        returns = [_number(point.get("net_return")) for point in points]
        output: list[dict[str, object]] = []
        for index, point in enumerate(points):
            first = max(0, index - window + 1)
            values = returns[first : index + 1]
            compounded = math.prod(1.0 + value for value in values) - 1.0
            volatility = 0.0
            sharpe = 0.0
            if len(values) > 1:
                mean = math.fsum(values) / len(values)
                variance = (
                    math.fsum((value - mean) ** 2 for value in values)
                    / (len(values) - 1)
                )
                standard_deviation = math.sqrt(max(variance, 0.0))
                volatility = standard_deviation * math.sqrt(annualization)
                if standard_deviation > 1e-15:
                    sharpe = (
                        mean / standard_deviation * math.sqrt(annualization)
                    )
            output.append(
                {
                    "session_date": _text(point.get("session_date")),
                    "fold_id": _text(point.get("fold_id")),
                    "window_periods": len(values),
                    "rolling_return": compounded,
                    "rolling_volatility": volatility,
                    "rolling_sharpe": sharpe,
                }
            )
        return output

    @staticmethod
    def _monthly(points: Sequence[Mapping[str, Any]]) -> list[dict[str, object]]:
        grouped: dict[str, list[Mapping[str, Any]]] = {}
        for point in points:
            month = _text(point.get("session_date"))[:7]
            if month:
                grouped.setdefault(month, []).append(point)
        output = []
        for month in sorted(grouped):
            values = grouped[month]
            output.append(
                {
                    "month": month,
                    "year": int(month[:4]),
                    "month_number": int(month[5:7]),
                    "net_return": math.prod(
                        1.0 + _number(value.get("net_return")) for value in values
                    )
                    - 1.0,
                    "gross_return": math.prod(
                        1.0 + _number(value.get("gross_return")) for value in values
                    )
                    - 1.0,
                    "periods": len(values),
                }
            )
        return output

    def analytics(
        self,
        validation_id: str,
        *,
        asset: str | None = None,
        start: date | None = None,
        end: date | None = None,
        fold_id: str | None = None,
        window: int = 20,
    ) -> dict[str, object]:
        self.item(validation_id)
        points = self._portfolio_points(
            validation_id,
            start=start,
            end=end,
            fold_id=fold_id,
        )
        portfolio = self.workspace_v2.portfolio_cockpit(validation_id)
        derived_rolling = _mapping(portfolio.get("derived_rolling"))
        annualization = _number(derived_rolling.get("annualization"))
        if annualization <= 0:
            raise ValueError("V4-4 A4 annualization must be positive")

        fee_cost = 0.0
        slippage_cost = 0.0
        desired = 0
        executable = 0
        filled = 0
        reason_counts: Counter[str] = Counter()
        row_count = 0
        for row in self._iter_decisions(
            validation_id,
            asset=asset,
            start=start,
            end=end,
            fold_id=fold_id,
        ):
            row_count += 1
            fee_cost += _number(row.get("fee_cost"))
            slippage_cost += _number(row.get("slippage_cost"))
            if abs(_number(row.get("desired_order_qty"))) > 1e-15:
                desired += 1
            if abs(_number(row.get("order_qty"))) > 1e-15:
                executable += 1
            if abs(_number(row.get("filled_qty"))) > 1e-15:
                filled += 1
            for key in ("order_reason_codes", "fill_reason_codes"):
                for reason in _sequence(row.get(key)):
                    text = _text(reason)
                    if text:
                        reason_counts[text] += 1

        return {
            "schema_version": PORTFOLIO_EXECUTION_ANALYTICS_SCHEMA,
            "read_only": True,
            "portfolio_validation_id": validation_id,
            "filters": {
                "asset": asset,
                "fold_id": fold_id,
                "start": start.isoformat() if start else None,
                "end": end.isoformat() if end else None,
                "window": window,
            },
            "drawdown": {
                "authority": "derived_presentation",
                "source_authority": "authoritative_a4_points",
                "formula": "nav / running_peak_nav - 1",
                "items": self._drawdown(points),
            },
            "rolling": {
                "authority": "derived_presentation",
                "source_authority": "authoritative_a4_net_returns",
                "annualization": annualization,
                "window": window,
                "items": self._rolling(
                    points,
                    annualization=annualization,
                    window=window,
                ),
            },
            "monthly_returns": {
                "authority": "derived_presentation",
                "source_authority": "authoritative_a4_period_returns",
                "formula": "product(1 + period_return) - 1 by calendar month",
                "items": self._monthly(points),
            },
            "filtered_costs": {
                "authority": "derived_presentation",
                "source_authority": "authoritative_v4_0_cost_rows",
                "fee_cost": fee_cost,
                "slippage_cost": slippage_cost,
                "total_cost": fee_cost + slippage_cost,
                "decision_row_count": row_count,
            },
            "order_funnel": {
                "authority": "derived_presentation",
                "source_authority": "authoritative_v4_0_order_quantity_rows",
                "desired": desired,
                "executable": executable,
                "filled": filled,
                "order_id_available": False,
            },
            "constraint_attribution": {
                "authority": "derived_presentation",
                "source_authority": "authoritative_v4_0_reason_code_rows",
                "reason_counts": dict(sorted(reason_counts.items())),
            },
            "benchmark": {
                "available": False,
                "authority": "unavailable_not_inferred",
                "note": (
                    "No immutable benchmark return/NAV evidence is persisted for V4-4"
                ),
            },
        }
