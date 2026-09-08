"""Candidate-aware linked Strategy/Portfolio/Execution projection for Workbench-2.

This is a disposable GET-only read model. It validates explicit persisted canonical
references between accepted R4 cycle evidence and existing MarketState, FactorLibrary,
experiment, StrategyDecisionSeries, A4 portfolio and V4-0 execution evidence. It never
constructs an AdaptiveStrategy, combines alpha, runs an allocator, derives attribution,
recomputes portfolio/PnL/cost, or guesses relationships from display names.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence
from typing import Any, cast
from urllib.parse import quote, urlencode

from .market_factor_intelligence import MarketFactorIntelligenceProjection
from .portfolio_execution import PortfolioExecutionInteractiveProjection
from .research_workspace import ResearchWorkspaceProjection
from .semantic import EvidenceContractError
from .strategy_explorer import StrategyDecisionExplorerProjection

LINKED_STRATEGY_INDEX_SCHEMA = "finagent.workspace.linked-strategy-index.v1"
LINKED_STRATEGY_DETAIL_SCHEMA = "finagent.workspace.linked-strategy-detail.v1"


def _object(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: object) -> Sequence[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return value
    return ()


def _text(value: object) -> str:
    return "" if value is None else str(value).strip()


def _query(path: str, **values: str | None) -> str:
    params = {key: value for key, value in values.items() if value}
    if not params:
        return path
    return f"{path}?{urlencode(params)}"


class LinkedStrategyAnalyticsProjection:
    """Validate explicit R4→historical-strategy lineage without creating authority."""

    def __init__(
        self,
        research_workspace: ResearchWorkspaceProjection,
        market_factor: MarketFactorIntelligenceProjection,
        strategy_explorer: StrategyDecisionExplorerProjection,
        portfolio_execution: PortfolioExecutionInteractiveProjection,
        *,
        evidence_ids: Sequence[str] = (),
    ) -> None:
        self.research_workspace = research_workspace
        self.market_factor = market_factor
        self.strategy_explorer = strategy_explorer
        self.portfolio_execution = portfolio_execution
        self.evidence_ids = frozenset(value for value in evidence_ids if value)

    def _cycles(self) -> list[dict[str, Any]]:
        return cast(list[dict[str, Any]], self.research_workspace.cycles()["items"])

    def _markets(self) -> list[dict[str, Any]]:
        return cast(list[dict[str, Any]], self.market_factor.markets()["items"])

    def _factors(self) -> list[dict[str, Any]]:
        return cast(list[dict[str, Any]], self.market_factor.factors()["items"])

    def _experiments(self) -> list[dict[str, Any]]:
        try:
            return cast(
                list[dict[str, Any]], self.research_workspace.experiments()["items"]
            )
        except (FileNotFoundError, sqlite3.Error, EvidenceContractError):
            return []

    def _strategy_items(self) -> list[dict[str, Any]]:
        return cast(list[dict[str, Any]], self.strategy_explorer.catalog()["items"])

    @staticmethod
    def _cycle_mode(cycle: Mapping[str, Any]) -> str:
        if cycle.get("accepted") is not True:
            return "not_accepted"
        return "candidate" if _text(cycle.get("candidate_id")) else "no_candidate"

    def index(self) -> dict[str, object]:
        cycles = [item for item in self._cycles() if item.get("accepted") is True]
        strategies = self._strategy_items()
        items = [
            {
                "cycle_id": cycle["cycle_id"],
                "terminal": cycle.get("terminal"),
                "agent_value": cycle.get("agent_value"),
                "candidate_id": cycle.get("candidate_id"),
                "mode": self._cycle_mode(cycle),
                "strategy_binding_status": (
                    "explicit_persisted_reference"
                    if isinstance(cycle.get("strategy_binding"), Mapping)
                    else "unavailable"
                ),
                "r5_eligible": bool(_object(cycle.get("authority")).get("r5_eligible")),
            }
            for cycle in cycles
        ]
        return {
            "schema_version": LINKED_STRATEGY_INDEX_SCHEMA,
            "items": items,
            "default_cycle_id": str(cycles[0]["cycle_id"]) if len(cycles) == 1 else None,
            "historical_strategy_series_count": len(strategies),
            "historical_strategy_relation": "unbound_unless_explicit_candidate_binding",
            "read_only": True,
            "canonical_identity_only": True,
            "browser_recomputation": False,
            "hidden_reasoning": "not_persisted_not_projected",
        }

    def cycle(self, cycle_id: str) -> dict[str, object]:
        cycle = next(
            (item for item in self._cycles() if _text(item.get("cycle_id")) == cycle_id),
            None,
        )
        if cycle is None:
            raise KeyError(cycle_id)

        markets = self._markets()
        factors = self._factors()
        experiments = self._experiments()
        strategies = self._strategy_items()
        market_ids = {_text(item.get("model_id")) for item in markets}
        factor_ids = {_text(item.get("factor_id")) for item in factors}
        experiment_by_id = {
            _text(item.get("experiment_id")): item
            for item in experiments
            if _text(item.get("experiment_id"))
        }
        strategy_by_id = {
            _text(item.get("series_id")): item
            for item in strategies
            if _text(item.get("series_id"))
        }
        experiment_run_ids = {
            _text(item.get("run_id")) for item in experiments if _text(item.get("run_id"))
        }
        mode = self._cycle_mode(cycle)
        candidate_id = _text(cycle.get("candidate_id")) or None
        economic = dict(_object(cycle.get("economic_evidence")))
        reliability = dict(_object(cycle.get("agent_reliability")))
        authority = dict(_object(cycle.get("authority")))
        binding = _object(cycle.get("strategy_binding"))
        unresolved: list[dict[str, str]] = []

        historical_strategies = [
            {
                "strategy_series_id": item.get("series_id"),
                "portfolio_validation_id": item.get("portfolio_validation_id"),
                "source_program_result_id": item.get("source_program_result_id"),
                "relation_to_cycle": "unbound_historical_evidence",
            }
            for item in strategies
        ]

        common: dict[str, object] = {
            "schema_version": LINKED_STRATEGY_DETAIL_SCHEMA,
            "cycle": {
                "cycle_id": cycle.get("cycle_id"),
                "accepted": cycle.get("accepted"),
                "review_disposition": cycle.get("review_disposition"),
                "terminal": cycle.get("terminal"),
                "agent_value": cycle.get("agent_value"),
                "candidate_id": candidate_id,
                "economic_evidence": economic,
                "agent_reliability": reliability,
                "authority": authority,
            },
            "mode": mode,
            "available_evidence": {
                "market_state_model_ids": sorted(value for value in market_ids if value),
                "factors": [
                    {"factor_id": item.get("factor_id"), "status": item.get("status")}
                    for item in factors
                ],
                "canonical_experiment_ids": sorted(experiment_by_id),
                "historical_strategy_series": historical_strategies,
            },
            "r5": {
                "status": (
                    "not_started_eligible"
                    if authority.get("r5_eligible") is True
                    else "not_started_not_eligible"
                ),
                "eligible": authority.get("r5_eligible") is True,
            },
            "read_only": True,
            "canonical_identity_only": True,
            "browser_recomputation": False,
            "hidden_reasoning": "not_persisted_not_projected",
        }

        if mode != "candidate":
            if binding:
                unresolved.append(
                    {
                        "relation": "candidate_strategy_binding",
                        "reason": "binding_ignored_without_accepted_candidate_identity",
                    }
                )
            common.update(
                {
                    "explanation": {
                        "reason": (
                            "accepted_cycle_has_no_adaptive_candidate"
                            if cycle.get("accepted") is True
                            else "cycle_not_explicitly_accepted"
                        ),
                        "economic_evidence_complete": economic.get(
                            "deterministic_evidence_complete"
                        ),
                        "basis": economic.get("interpretation"),
                        "claims_not_supported": [
                            "all_strategies_lost_money",
                            "market_state_failed",
                            "agent_proved_ineffective",
                        ],
                    },
                    "candidate": None,
                    "strategy_binding": {
                        "status": "unavailable",
                        "reason": "accepted_cycle_has_no_adaptive_candidate"
                        if cycle.get("accepted") is True
                        else "cycle_not_explicitly_accepted",
                    },
                    "combined_strategy_evidence": {
                        "available": False,
                        "reason": "no_persisted_candidate_strategy_binding",
                    },
                    "target_portfolio": {
                        "available": False,
                        "reason": "no_persisted_candidate_strategy_binding",
                    },
                    "execution_pnl": {
                        "available": False,
                        "reason": "no_persisted_candidate_strategy_binding",
                    },
                    "attribution": {
                        "available": False,
                        "reason": "unavailable_not_persisted",
                    },
                    "links": {
                        "research_graph": _query(
                            "/research-graph", cycle=cycle_id
                        ),
                    },
                    "unresolved": unresolved,
                }
            )
            return common

        if not binding:
            unresolved.append(
                {
                    "relation": "candidate_strategy_binding",
                    "reason": "explicit_persisted_binding_unavailable",
                }
            )

        binding_candidate = _text(binding.get("candidate_id"))
        if binding and binding_candidate != candidate_id:
            unresolved.append(
                {
                    "relation": "candidate_identity",
                    "reason": "binding_candidate_id_mismatch",
                }
            )
            binding = {}

        strategy_series_id = _text(binding.get("strategy_series_id"))
        portfolio_validation_id = _text(binding.get("portfolio_validation_id"))
        market_state_model_id = _text(binding.get("market_state_model_id"))
        bound_factor_ids = [
            _text(value) for value in _sequence(binding.get("factor_ids")) if _text(value)
        ]
        bound_experiment_ids = [
            _text(value)
            for value in _sequence(binding.get("experiment_ids"))
            if _text(value)
        ]
        bound_evidence_ids = [
            _text(value) for value in _sequence(binding.get("evidence_ids")) if _text(value)
        ]
        agent_run_id = _text(binding.get("agent_run_id"))
        attribution_evidence_id = _text(binding.get("attribution_evidence_id"))

        strategy_item = strategy_by_id.get(strategy_series_id)
        if not strategy_series_id:
            unresolved.append(
                {
                    "relation": "strategy_series",
                    "reason": "strategy_series_id_unavailable_in_binding",
                }
            )
        elif strategy_item is None:
            unresolved.append(
                {
                    "relation": "strategy_series",
                    "reason": "strategy_series_identity_not_available",
                }
            )

        portfolio_item: dict[str, Any] | None = None
        if not portfolio_validation_id:
            unresolved.append(
                {
                    "relation": "target_portfolio",
                    "reason": "portfolio_validation_id_unavailable_in_binding",
                }
            )
        elif strategy_item is not None and _text(
            strategy_item.get("portfolio_validation_id")
        ) != portfolio_validation_id:
            unresolved.append(
                {
                    "relation": "strategy_to_portfolio",
                    "reason": "binding_portfolio_does_not_match_strategy_manifest",
                }
            )
        else:
            try:
                portfolio_item = self.portfolio_execution.item(
                    portfolio_validation_id
                ).to_dict()
            except KeyError:
                unresolved.append(
                    {
                        "relation": "target_portfolio",
                        "reason": "portfolio_execution_identity_not_available",
                    }
                )

        if market_state_model_id and market_state_model_id not in market_ids:
            unresolved.append(
                {
                    "relation": "market_state",
                    "reason": "market_state_model_identity_not_available",
                }
            )
        for factor_id in bound_factor_ids:
            if factor_id not in factor_ids:
                unresolved.append(
                    {
                        "relation": f"factor:{factor_id}",
                        "reason": "factor_identity_not_available",
                    }
                )
        for experiment_id in bound_experiment_ids:
            if experiment_id not in experiment_by_id:
                unresolved.append(
                    {
                        "relation": f"experiment:{experiment_id}",
                        "reason": "experiment_identity_not_available_in_current_audit",
                    }
                )
        for evidence_id in bound_evidence_ids:
            if evidence_id not in self.evidence_ids:
                unresolved.append(
                    {
                        "relation": f"evidence:{evidence_id}",
                        "reason": "evidence_identity_not_available_in_catalog",
                    }
                )
        if agent_run_id and agent_run_id not in experiment_run_ids:
            unresolved.append(
                {
                    "relation": "agent_run",
                    "reason": "agent_run_identity_not_available_in_current_audit",
                }
            )

        strategy_available = strategy_item is not None
        portfolio_available = portfolio_item is not None
        core_available = strategy_available and portfolio_available
        binding_status = (
            "resolved"
            if core_available and not unresolved
            else "partial"
            if core_available
            else "unavailable"
        )

        historical_strategies = [
            {
                **item,
                "relation_to_cycle": (
                    "explicit_candidate_binding"
                    if _text(item.get("strategy_series_id")) == strategy_series_id
                    else "unbound_historical_evidence"
                ),
            }
            for item in historical_strategies
        ]
        common["available_evidence"] = {
            **cast(dict[str, object], common["available_evidence"]),
            "historical_strategy_series": historical_strategies,
        }
        common.update(
            {
                "explanation": {
                    "reason": "accepted_development_candidate_persisted",
                    "binding_semantics": "explicit_canonical_references_only",
                    "claims_not_supported": [
                        "r5_confirmed",
                        "paper_accepted",
                        "live_authorized",
                    ],
                },
                "candidate": {
                    "candidate_id": candidate_id,
                    "binding_id": binding.get("binding_id") if binding else None,
                    "market_state_model_id": market_state_model_id or None,
                    "factor_ids": bound_factor_ids,
                    "experiment_ids": bound_experiment_ids,
                    "agent_run_id": agent_run_id or None,
                    "evidence_ids": bound_evidence_ids,
                },
                "strategy_binding": {
                    "status": binding_status,
                    "binding": dict(binding) if binding else None,
                },
                "combined_strategy_evidence": {
                    "available": strategy_available,
                    "strategy_series_id": strategy_series_id or None,
                    "selected_feature_digests": (
                        strategy_item.get("selected_feature_digests")
                        if strategy_item is not None
                        else None
                    ),
                    "alpha_model_ids": (
                        strategy_item.get("alpha_model_ids")
                        if strategy_item is not None
                        else None
                    ),
                    "authority": (
                        "authoritative_v4_0_strategy_decision_rows"
                        if strategy_available
                        else "unavailable_not_inferred"
                    ),
                },
                "target_portfolio": {
                    "available": portfolio_available,
                    "portfolio_validation_id": portfolio_validation_id or None,
                    "authority": (
                        "authoritative_a4_report"
                        if portfolio_available
                        else "unavailable_not_inferred"
                    ),
                },
                "execution_pnl": {
                    "available": portfolio_available,
                    "portfolio_validation_id": portfolio_validation_id or None,
                    "authority": (
                        "authoritative_v4_0_strategy_decision_rows"
                        if portfolio_available
                        else "unavailable_not_inferred"
                    ),
                },
                "attribution": {
                    "available": bool(
                        attribution_evidence_id
                        and attribution_evidence_id in self.evidence_ids
                    ),
                    "evidence_id": attribution_evidence_id or None,
                    "reason": (
                        None
                        if attribution_evidence_id
                        and attribution_evidence_id in self.evidence_ids
                        else "unavailable_not_persisted"
                    ),
                },
                "links": {
                    "market": (
                        _query(
                            "/market",
                            market_model=market_state_model_id,
                            cycle=cycle_id,
                            strategy=candidate_id,
                        )
                        if market_state_model_id
                        else None
                    ),
                    "factors": [
                        _query(
                            "/factors",
                            factor=factor_id,
                            cycle=cycle_id,
                            strategy=candidate_id,
                        )
                        for factor_id in bound_factor_ids
                    ],
                    "experiments": [
                        _query(
                            "/experiments",
                            experiment=experiment_id,
                            cycle=cycle_id,
                            strategy=candidate_id,
                        )
                        for experiment_id in bound_experiment_ids
                    ],
                    "strategy": (
                        _query(
                            f"/strategy/{quote(strategy_series_id, safe='')}",
                            strategy=candidate_id,
                            cycle=cycle_id,
                            portfolio=portfolio_validation_id or None,
                        )
                        if strategy_series_id
                        else _query("/strategy", strategy=candidate_id, cycle=cycle_id)
                    ),
                    "portfolio": (
                        _query(
                            f"/portfolio/{quote(portfolio_validation_id, safe='')}",
                            portfolio=portfolio_validation_id,
                            strategy=candidate_id,
                            cycle=cycle_id,
                        )
                        if portfolio_validation_id
                        else None
                    ),
                    "execution": (
                        _query(
                            f"/execution/{quote(portfolio_validation_id, safe='')}",
                            portfolio=portfolio_validation_id,
                            strategy=candidate_id,
                            cycle=cycle_id,
                        )
                        if portfolio_validation_id
                        else None
                    ),
                    "research_graph": _query(
                        "/research-graph", cycle=cycle_id, strategy=candidate_id
                    ),
                    "agent": (
                        _query("/agent", run=agent_run_id, strategy=candidate_id)
                        if agent_run_id
                        else None
                    ),
                    "evidence": [
                        f"/evidence/{quote(evidence_id, safe='')}"
                        for evidence_id in bound_evidence_ids
                    ],
                },
                "unresolved": unresolved,
            }
        )
        return common

    def status(self) -> dict[str, object]:
        index = self.index()
        items = cast(list[dict[str, Any]], index["items"])
        return {
            "schema_version": "finagent.workspace.linked-strategy-status.v1",
            "accepted_cycle_count": len(items),
            "candidate_cycle_count": sum(item.get("mode") == "candidate" for item in items),
            "no_candidate_cycle_count": sum(item.get("mode") == "no_candidate" for item in items),
            "read_only": True,
            "canonical_identity_only": True,
            "browser_recomputation": False,
            "hidden_reasoning": "not_persisted_not_projected",
        }
