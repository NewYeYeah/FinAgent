from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .factor_tearsheet import FactorTearSheetProjection
from .portfolio_execution import PortfolioExecutionInteractiveProjection
from .strategy_explorer import StrategyDecisionExplorerProjection

LINKED_ANALYTICS_ACCEPTANCE_SCHEMA = "finagent.linked-analytics-acceptance.status.v1"
LINKED_ANALYTICS_BROWSER_ROW_LIMIT = 5000

LINKED_ANALYTICS_CONTEXT_KEYS = (
    "program_id",
    "factor_id",
    "portfolio_validation_id",
    "asset_id",
    "order_id",
    "date_range",
    "session_date",
    "fold_id",
)


@dataclass(frozen=True, slots=True)
class LinkedAnalyticsSurfaceContract:
    surface: str
    routes: tuple[str, ...]
    required_evidence: tuple[str, ...]
    authoritative_sources: tuple[str, ...]
    derived_presentation: tuple[str, ...]
    unavailable_not_inferred: tuple[str, ...]
    context_keys: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "surface": self.surface,
            "routes": list(self.routes),
            "required_evidence": list(self.required_evidence),
            "authoritative_sources": list(self.authoritative_sources),
            "derived_presentation": list(self.derived_presentation),
            "unavailable_not_inferred": list(self.unavailable_not_inferred),
            "context_keys": list(self.context_keys),
            "browser_recomputation": False,
        }


SURFACE_CONTRACTS = (
    LinkedAnalyticsSurfaceContract(
        surface="strategy",
        routes=("/strategy", "/strategy/:seriesId"),
        required_evidence=("StrategyDecisionSeriesEvidence V4-0",),
        authoritative_sources=(
            "V4-0 close/reference/fill price rows",
            "V4-0 alpha/target/realized weight rows",
            "V4-0 desired/executable/filled quantity rows",
            "V4-0 fees/slippage/gross/net PnL rows",
            "V4-0 decision status/client_order_id/constraint_codes rows",
            "A-C2 MarketBarSeriesEvidence raw OHLCV when explicitly bound",
        ),
        derived_presentation=(),
        unavailable_not_inferred=(
            "OHLC candlesticks when no verified MarketBarSeriesEvidence is bound",
            "per-asset per-factor contribution",
        ),
        context_keys=(
            "portfolio_validation_id",
            "asset_id",
            "date_range",
            "session_date",
            "fold_id",
        ),
    ),
    LinkedAnalyticsSurfaceContract(
        surface="factors",
        routes=("/factors", "/factors/:seriesId"),
        required_evidence=(
            "FactorSeriesEvidence V4-1",
            "frozen A2.6 ResearchProgram summary",
        ),
        authoritative_sources=(
            "V4-1 period IC/RankIC/turnover/coverage rows",
            "V4-1 persisted derived rolling/NAV rows",
            "frozen A2.6 inference/multiplicity/gate/correlation summary",
        ),
        derived_presentation=(
            "fold/year IC means",
            "factor correlation cluster ordering",
        ),
        unavailable_not_inferred=("Agent generation chronology",),
        context_keys=(
            "program_id",
            "factor_id",
            "date_range",
            "fold_id",
        ),
    ),
    LinkedAnalyticsSurfaceContract(
        surface="portfolio",
        routes=("/portfolio", "/portfolio/:validationId"),
        required_evidence=(
            "authoritative A4 portfolio validation evidence",
            "verified StrategyDecisionSeriesEvidence V4-0",
        ),
        authoritative_sources=(
            "A4 gross/net NAV and period returns",
            "A4 frozen aggregate/fold/economic metrics",
            "A4 execution-ledger identity",
        ),
        derived_presentation=(
            "drawdown",
            "rolling return/volatility/Sharpe",
            "calendar monthly return matrix",
            "filtered cost totals",
        ),
        unavailable_not_inferred=(
            "benchmark return/NAV",
            "benchmark-relative alpha/beta/information ratio",
            "industry/style exposure",
            "capacity",
            "risk contribution",
        ),
        context_keys=(
            "portfolio_validation_id",
            "asset_id",
            "order_id",
            "date_range",
            "session_date",
            "fold_id",
        ),
    ),
    LinkedAnalyticsSurfaceContract(
        surface="execution",
        routes=("/execution", "/execution/:validationId"),
        required_evidence=(
            "verified StrategyDecisionSeriesEvidence V4-0",
            "authoritative A3 decision semantics persisted in V4-0 rows",
        ),
        authoritative_sources=(
            "target/realized weights",
            "client_order_id",
            "desired/executable/filled quantities",
            "reference/fill/close prices",
            "fees/slippage/gross/net PnL",
            "decision status and constraint_codes",
        ),
        derived_presentation=(
            "desired/executable/filled funnel",
            "constraint-code counts",
            "filtered fee/slippage totals",
        ),
        unavailable_not_inferred=(
            "capacity/impact model",
            "broker/live account state",
        ),
        context_keys=(
            "portfolio_validation_id",
            "asset_id",
            "order_id",
            "date_range",
            "session_date",
            "fold_id",
        ),
    ),
)


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


class LinkedAnalyticsAcceptanceProjection:
    """Machine-readable acceptance contract for the linked analytical Workbench.

    A-C2 extends Strategy with optional authoritative MarketBarSeriesEvidence without
    changing the V4-0 strategy/execution authority. Missing OHLC remains explicit and
    never becomes a reason to synthesize bars in the browser.
    """

    def __init__(
        self,
        strategy_explorer: StrategyDecisionExplorerProjection,
        factor_tearsheet: FactorTearSheetProjection,
        portfolio_execution: PortfolioExecutionInteractiveProjection,
    ) -> None:
        self.strategy_explorer = strategy_explorer
        self.factor_tearsheet = factor_tearsheet
        self.portfolio_execution = portfolio_execution

    def runtime_checks(self) -> dict[str, bool]:
        strategy = _mapping(self.strategy_explorer.status())
        factors = _mapping(self.factor_tearsheet.status())
        portfolio = _mapping(self.portfolio_execution.status())
        ohlc_available = strategy.get("ohlc_available") is True
        ohlc_authority = strategy.get("ohlc_authority")
        return {
            "strategy_read_only": strategy.get("read_only") is True,
            "strategy_no_browser_recomputation": (
                strategy.get("browser_recomputation") is False
            ),
            "strategy_ohlc_authority_is_explicit": (
                (ohlc_available and ohlc_authority == "MarketBarSeriesEvidence")
                or (not ohlc_available and ohlc_authority == "unavailable")
            ),
            "factors_read_only": factors.get("read_only") is True,
            "factors_no_browser_recomputation": (
                factors.get("browser_recomputation") is False
            ),
            "factors_missing_agent_chronology_is_explicit": (
                factors.get("agent_chronology_available") is False
            ),
            "portfolio_execution_read_only": portfolio.get("read_only") is True,
            "portfolio_execution_no_browser_recomputation": (
                portfolio.get("browser_recomputation") is False
            ),
            "portfolio_missing_benchmark_is_explicit": (
                portfolio.get("benchmark_available") is False
            ),
            "execution_order_identity_is_available": (
                portfolio.get("order_id_available") is True
            ),
        }

    def status(self) -> dict[str, object]:
        checks = self.runtime_checks()
        return {
            "schema_version": LINKED_ANALYTICS_ACCEPTANCE_SCHEMA,
            "read_only": True,
            "accepted": all(checks.values()),
            "authority": "acceptance_contract_only_no_financial_authority",
            "browser_recomputation": False,
            "evidence_plane_methods": ["GET", "HEAD", "OPTIONS"],
            "control_authority_ceiling": ["L0", "L1"],
            "browser_row_limit": LINKED_ANALYTICS_BROWSER_ROW_LIMIT,
            "server_side_pagination_required_for_full_aggregates": True,
            "context_keys": list(LINKED_ANALYTICS_CONTEXT_KEYS),
            "context_semantics": (
                "URL-backed presentation identity; values are preserved across module "
                "navigation/history/reload and never reinterpret evidence identity"
            ),
            "missing_evidence_policy": "explicit_unavailable_not_inferred",
            "surfaces": [contract.to_dict() for contract in SURFACE_CONTRACTS],
            "runtime_checks": checks,
        }
