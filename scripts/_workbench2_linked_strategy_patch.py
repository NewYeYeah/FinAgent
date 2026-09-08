from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"missing patch anchor in {path}: {old[:120]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def replace_all(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"missing patch anchor in {path}: {old[:120]!r}")
    target.write_text(text.replace(old, new), encoding="utf-8")


# Research cycle binding is persisted-reference only and fail-closed.
replace_once(
    "src/finagent/visualization/research_workspace.py",
    '_FAILED_OUTCOMES = {"TOOL_FAILED", "EVALUATOR_TIMEOUT", "AUDIT_FAILED"}\n',
    '_FAILED_OUTCOMES = {"TOOL_FAILED", "EVALUATOR_TIMEOUT", "AUDIT_FAILED"}\n_LINKED_STRATEGY_BINDING_SCHEMA = "finagent.workbench-linked-strategy-binding.v1"\n',
)

old_cycles = '''    def cycles(self) -> dict[str, object]:
        items: list[dict[str, Any]] = []
        unresolved: list[dict[str, Any]] = []
        seen: set[str] = set()
        for root in self.cycle_paths:
            candidates = (
                (root,) if root.is_file() else tuple(root.rglob("campaign_result_attestation.json"))
                if root.is_dir()
                else ()
            )
            for path in candidates:
                try:
                    value = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if not isinstance(value, Mapping) or not str(value.get("schema_version", "")).startswith(
                    "finagent.r4-campaign-result-attestation."
                ):
                    continue
                cycle_id = str(value.get("campaign_result_id", "")).strip()
                if not cycle_id or cycle_id in seen:
                    continue
                seen.add(cycle_id)
                resource_path = path.with_name("resource_summary.json")
                resources: Mapping[str, Any] = {}
                if resource_path.is_file():
                    try:
                        loaded = json.loads(resource_path.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError):
                        loaded = {}
                    resources = loaded if isinstance(loaded, Mapping) else {}
                accepted = value.get("review_disposition") == "R4_RESULT_ACCEPTED"
                if not accepted:
                    unresolved.append(
                        {
                            "cycle_id": cycle_id,
                            "relation": "review_disposition",
                            "reason": "accepted_review_disposition_missing_or_unrecognized",
                        }
                    )
                items.append(
                    {
                        "cycle_id": cycle_id,
                        "accepted": accepted,
                        "review_status": "accepted" if accepted else "not_accepted",
                        "protocol_id": value.get("protocol_id"),
                        "protocol_version": value.get("protocol_version"),
                        "review_disposition": value.get("review_disposition"),
                        "terminal": value.get("candidate_decision"),
                        "agent_value": value.get("agent_value"),
                        "candidate_id": value.get("candidate_id"),
                        "economic_evidence": dict(_object(value.get("economic_evidence"))),
                        "provider_usage": dict(_object(value.get("provider_usage"))),
                        "agent_reliability": dict(_object(value.get("agent_reliability"))),
                        "resource_summary": dict(resources),
                        "authority": {
                            "development_only": bool(value.get("development_only", True)),
                            "alpha_authority": bool(value.get("alpha_authority", False)),
                            "paper_authority": bool(value.get("paper_authority", False)),
                            "live_authority": bool(value.get("live_authority", False)),
                            "r5_eligible": bool(value.get("r5_eligible", False)),
                        },
                        "evidence": {
                            "attestation_path": path.as_posix(),
                            "resource_summary_path": resource_path.as_posix()
                            if resource_path.is_file()
                            else None,
                            "campaign_freeze_id": value.get("campaign_freeze_id"),
                            "provider_admission_id": value.get("provider_admission_id"),
                            "research_admission_id": value.get("research_admission_id"),
                        },
                    }
                )
        items.sort(key=lambda item: item["cycle_id"])
        return {
            "schema_version": "finagent.workspace.research-cycles.v1",
            "items": items,
            "unresolved": unresolved,
            "read_only": True,
            "browser_recomputation": False,
        }
'''
new_cycles = '''    def _strategy_bindings(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        items: list[dict[str, Any]] = []
        unresolved: list[dict[str, Any]] = []
        seen: dict[str, dict[str, Any]] = {}
        for root in self.cycle_paths:
            candidates = (
                (root,)
                if root.is_file() and root.name == "linked_strategy_binding.json"
                else tuple(root.rglob("linked_strategy_binding.json"))
                if root.is_dir()
                else ()
            )
            for path in candidates:
                try:
                    value = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    unresolved.append(
                        {
                            "relation": "strategy_binding",
                            "reason": "persisted_binding_unreadable",
                            "path": path.as_posix(),
                        }
                    )
                    continue
                if not isinstance(value, Mapping) or value.get("schema_version") != _LINKED_STRATEGY_BINDING_SCHEMA:
                    continue
                binding_id = str(value.get("binding_id", "")).strip()
                cycle_id = str(value.get("cycle_id", "")).strip()
                candidate_id = str(value.get("candidate_id", "")).strip()
                if not binding_id or not cycle_id or not candidate_id:
                    unresolved.append(
                        {
                            "relation": "strategy_binding",
                            "reason": "binding_identity_cycle_candidate_required",
                            "path": path.as_posix(),
                        }
                    )
                    continue
                item: dict[str, Any] = {
                    "schema_version": _LINKED_STRATEGY_BINDING_SCHEMA,
                    "binding_id": binding_id,
                    "cycle_id": cycle_id,
                    "candidate_id": candidate_id,
                    "strategy_series_id": str(value.get("strategy_series_id", "") or "").strip() or None,
                    "portfolio_validation_id": str(value.get("portfolio_validation_id", "") or "").strip() or None,
                    "market_state_model_id": str(value.get("market_state_model_id", "") or "").strip() or None,
                    "factor_ids": _unique(value.get("factor_ids", ()) if isinstance(value.get("factor_ids"), Sequence) and not isinstance(value.get("factor_ids"), (str, bytes)) else ()),
                    "experiment_ids": _unique(value.get("experiment_ids", ()) if isinstance(value.get("experiment_ids"), Sequence) and not isinstance(value.get("experiment_ids"), (str, bytes)) else ()),
                    "evidence_ids": _unique(value.get("evidence_ids", ()) if isinstance(value.get("evidence_ids"), Sequence) and not isinstance(value.get("evidence_ids"), (str, bytes)) else ()),
                    "agent_run_id": str(value.get("agent_run_id", "") or "").strip() or None,
                    "attribution_evidence_id": str(value.get("attribution_evidence_id", "") or "").strip() or None,
                    "source_path": path.as_posix(),
                    "read_only_reference": True,
                }
                previous = seen.get(binding_id)
                if previous is not None and previous != item:
                    unresolved.append(
                        {
                            "binding_id": binding_id,
                            "cycle_id": cycle_id,
                            "relation": "strategy_binding",
                            "reason": "conflicting_payloads_share_binding_id",
                        }
                    )
                    continue
                if previous is None:
                    seen[binding_id] = item
                    items.append(item)
        return items, unresolved

    def cycles(self) -> dict[str, object]:
        items: list[dict[str, Any]] = []
        bindings, unresolved = self._strategy_bindings()
        seen: set[str] = set()
        for root in self.cycle_paths:
            candidates = (
                (root,) if root.is_file() and root.name == "campaign_result_attestation.json" else tuple(root.rglob("campaign_result_attestation.json"))
                if root.is_dir()
                else ()
            )
            for path in candidates:
                try:
                    value = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if not isinstance(value, Mapping) or not str(value.get("schema_version", "")).startswith(
                    "finagent.r4-campaign-result-attestation."
                ):
                    continue
                cycle_id = str(value.get("campaign_result_id", "")).strip()
                if not cycle_id or cycle_id in seen:
                    continue
                seen.add(cycle_id)
                resource_path = path.with_name("resource_summary.json")
                resources: Mapping[str, Any] = {}
                if resource_path.is_file():
                    try:
                        loaded = json.loads(resource_path.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError):
                        loaded = {}
                    resources = loaded if isinstance(loaded, Mapping) else {}
                accepted = value.get("review_disposition") == "R4_RESULT_ACCEPTED"
                candidate_id = str(value.get("candidate_id", "") or "").strip() or None
                if not accepted:
                    unresolved.append(
                        {
                            "cycle_id": cycle_id,
                            "relation": "review_disposition",
                            "reason": "accepted_review_disposition_missing_or_unrecognized",
                        }
                    )
                cycle_bindings = [item for item in bindings if item["cycle_id"] == cycle_id]
                strategy_binding: dict[str, Any] | None = None
                if cycle_bindings:
                    if not accepted:
                        unresolved.append(
                            {
                                "cycle_id": cycle_id,
                                "relation": "strategy_binding",
                                "reason": "binding_ignored_for_cycle_not_explicitly_accepted",
                            }
                        )
                    elif candidate_id is None:
                        unresolved.append(
                            {
                                "cycle_id": cycle_id,
                                "relation": "strategy_binding",
                                "reason": "binding_ignored_for_accepted_no_candidate_cycle",
                            }
                        )
                    elif len(cycle_bindings) != 1:
                        unresolved.append(
                            {
                                "cycle_id": cycle_id,
                                "relation": "strategy_binding",
                                "reason": "multiple_bindings_for_cycle",
                            }
                        )
                    elif cycle_bindings[0]["candidate_id"] != candidate_id:
                        unresolved.append(
                            {
                                "cycle_id": cycle_id,
                                "relation": "strategy_binding",
                                "reason": "binding_candidate_id_mismatch",
                            }
                        )
                    else:
                        strategy_binding = dict(cycle_bindings[0])
                items.append(
                    {
                        "cycle_id": cycle_id,
                        "accepted": accepted,
                        "review_status": "accepted" if accepted else "not_accepted",
                        "protocol_id": value.get("protocol_id"),
                        "protocol_version": value.get("protocol_version"),
                        "review_disposition": value.get("review_disposition"),
                        "terminal": value.get("candidate_decision"),
                        "agent_value": value.get("agent_value"),
                        "candidate_id": candidate_id,
                        "strategy_binding": strategy_binding,
                        "economic_evidence": dict(_object(value.get("economic_evidence"))),
                        "provider_usage": dict(_object(value.get("provider_usage"))),
                        "agent_reliability": dict(_object(value.get("agent_reliability"))),
                        "resource_summary": dict(resources),
                        "authority": {
                            "development_only": bool(value.get("development_only", True)),
                            "alpha_authority": bool(value.get("alpha_authority", False)),
                            "paper_authority": bool(value.get("paper_authority", False)),
                            "live_authority": bool(value.get("live_authority", False)),
                            "r5_eligible": bool(value.get("r5_eligible", False)),
                        },
                        "evidence": {
                            "attestation_path": path.as_posix(),
                            "resource_summary_path": resource_path.as_posix()
                            if resource_path.is_file()
                            else None,
                            "campaign_freeze_id": value.get("campaign_freeze_id"),
                            "provider_admission_id": value.get("provider_admission_id"),
                            "research_admission_id": value.get("research_admission_id"),
                        },
                    }
                )
        items.sort(key=lambda item: item["cycle_id"])
        return {
            "schema_version": "finagent.workspace.research-cycles.v1",
            "items": items,
            "unresolved": unresolved,
            "read_only": True,
            "browser_recomputation": False,
        }
'''
replace_once("src/finagent/visualization/research_workspace.py", old_cycles, new_cycles)

old_graph_cycle = '''        cycle_items = cast(list[dict[str, Any]], self.cycles()["items"])
        for cycle in cycle_items:
            cycle_id = str(cycle["cycle_id"])
            if cycle.get("accepted") is not True:
                unresolved.append(
                    {
                        "cycle_id": cycle_id,
                        "relation": "accepted_cycle_lineage",
                        "reason": "cycle_not_explicitly_accepted",
                    }
                )
                continue
            cycle_node = node(
                "research_cycle",
                cycle_id,
                label=str(cycle.get("protocol_version") or cycle_id),
                status="accepted",
                details={"protocol_id": cycle.get("protocol_id")},
            )
            economic = _object(cycle.get("economic_evidence"))
            evaluation_node = node(
                "evaluation",
                cycle_id,
                label="Economic evidence completeness",
                status="incomplete" if economic.get("deterministic_evidence_complete") is False else "complete",
                details=economic,
            )
            terminal = str(cycle.get("terminal", ""))
            if terminal:
                terminal_node = node(
                    "terminal",
                    cycle_id,
                    label=terminal,
                    status="accepted_terminal",
                    details={
                        "agent_value": cycle.get("agent_value"),
                        "candidate_id": cycle.get("candidate_id"),
                        "agent_reliability": cycle.get("agent_reliability"),
                    },
                )
                edge(cycle_node, evaluation_node, "attests_economic_evidence")
                edge(evaluation_node, terminal_node, "supports_terminal")
            unresolved.append(
                {
                    "cycle_id": cycle_id,
                    "relation": "campaign_run_experiment_lineage",
                    "reason": "accepted_attestation_does_not_embed_run_local_experiment_identities",
                }
            )
'''
new_graph_cycle = '''        cycle_items = cast(list[dict[str, Any]], self.cycles()["items"])
        for cycle in cycle_items:
            cycle_id = str(cycle["cycle_id"])
            if cycle.get("accepted") is not True:
                unresolved.append(
                    {
                        "cycle_id": cycle_id,
                        "relation": "accepted_cycle_lineage",
                        "reason": "cycle_not_explicitly_accepted",
                    }
                )
                continue
            cycle_context = {"research_cycle_id": cycle_id}
            cycle_href = f"/strategy?cycle={quote(cycle_id, safe='')}"
            cycle_node = node(
                "research_cycle",
                cycle_id,
                label=str(cycle.get("protocol_version") or cycle_id),
                status="accepted",
                href=cycle_href,
                context=cycle_context,
                details={"protocol_id": cycle.get("protocol_id")},
            )
            economic = _object(cycle.get("economic_evidence"))
            evaluation_node = node(
                "evaluation",
                cycle_id,
                label="Economic evidence completeness",
                status="incomplete" if economic.get("deterministic_evidence_complete") is False else "complete",
                context=cycle_context,
                details=economic,
            )
            terminal = str(cycle.get("terminal", ""))
            terminal_node: str | None = None
            if terminal:
                terminal_node = node(
                    "terminal",
                    cycle_id,
                    label=terminal,
                    status="accepted_terminal",
                    href=cycle_href,
                    context=cycle_context,
                    details={
                        "agent_value": cycle.get("agent_value"),
                        "candidate_id": cycle.get("candidate_id"),
                        "agent_reliability": cycle.get("agent_reliability"),
                    },
                )
                edge(cycle_node, evaluation_node, "attests_economic_evidence")
                edge(evaluation_node, terminal_node, "supports_terminal")
            binding = _object(cycle.get("strategy_binding"))
            candidate_id = str(cycle.get("candidate_id", "") or "").strip()
            if binding and candidate_id:
                strategy_context = {
                    "research_cycle_id": cycle_id,
                    "strategy_id": candidate_id,
                }
                candidate_node = node(
                    "strategy_candidate",
                    candidate_id,
                    label=f"AdaptiveStrategy candidate · {candidate_id}",
                    status="development_candidate",
                    href=f"/strategy?strategy={quote(candidate_id, safe='')}&cycle={quote(cycle_id, safe='')}",
                    context=strategy_context,
                    details={
                        "binding_id": binding.get("binding_id"),
                        "strategy_series_id": binding.get("strategy_series_id"),
                        "portfolio_validation_id": binding.get("portfolio_validation_id"),
                    },
                )
                if terminal_node is not None:
                    edge(terminal_node, candidate_node, "candidate_terminal")
                model_id = str(binding.get("market_state_model_id", "") or "").strip()
                if model_id:
                    market_node = node(
                        "market_state",
                        model_id,
                        href=f"/market?market_model={quote(model_id, safe='')}",
                        context={**strategy_context, "market_state_model_id": model_id},
                    )
                    edge(market_node, candidate_node, "candidate_market_state")
                for factor_id in _unique(binding.get("factor_ids", ())):
                    factor_node = node(
                        "factor",
                        factor_id,
                        href=f"/factors?factor={quote(factor_id, safe='')}",
                        context={**strategy_context, "factor_id": factor_id},
                    )
                    edge(factor_node, candidate_node, "candidate_factor")
                for experiment_id in _unique(binding.get("experiment_ids", ())):
                    experiment_node = node(
                        "experiment",
                        experiment_id,
                        href=f"/experiments?experiment={quote(experiment_id, safe='')}",
                        context={**strategy_context, "experiment_id": experiment_id},
                    )
                    edge(experiment_node, candidate_node, "supports_candidate")
                strategy_series_id = str(binding.get("strategy_series_id", "") or "").strip()
                portfolio_id = str(binding.get("portfolio_validation_id", "") or "").strip()
                strategy_node: str | None = None
                if strategy_series_id:
                    strategy_node = node(
                        "strategy",
                        strategy_series_id,
                        label=f"Strategy evidence · {strategy_series_id}",
                        href=f"/strategy/{quote(strategy_series_id, safe='')}?strategy={quote(candidate_id, safe='')}&cycle={quote(cycle_id, safe='')}",
                        context={**strategy_context, "portfolio_validation_id": portfolio_id} if portfolio_id else strategy_context,
                        details={"binding_id": binding.get("binding_id")},
                    )
                    edge(candidate_node, strategy_node, "explicit_persisted_binding")
                else:
                    unresolved.append(
                        {
                            "cycle_id": cycle_id,
                            "relation": "candidate_strategy_series",
                            "reason": "explicit_strategy_series_id_unavailable",
                        }
                    )
                if portfolio_id:
                    portfolio_context = {
                        **strategy_context,
                        "portfolio_validation_id": portfolio_id,
                    }
                    portfolio_node = node(
                        "portfolio",
                        portfolio_id,
                        href=f"/portfolio/{quote(portfolio_id, safe='')}",
                        context=portfolio_context,
                    )
                    execution_node = node(
                        "execution",
                        portfolio_id,
                        label=f"Execution evidence · {portfolio_id}",
                        href=f"/execution/{quote(portfolio_id, safe='')}",
                        context=portfolio_context,
                    )
                    edge(strategy_node or candidate_node, portfolio_node, "targets_portfolio")
                    edge(portfolio_node, execution_node, "historical_execution")
                agent_run_id = str(binding.get("agent_run_id", "") or "").strip()
                if agent_run_id:
                    agent_node = node(
                        "agent_run",
                        agent_run_id,
                        href=f"/agent?run={quote(agent_run_id, safe='')}",
                        context={**strategy_context, "run_id": agent_run_id},
                    )
                    edge(agent_node, candidate_node, "agent_candidate_decision")
                for evidence_id in _unique(binding.get("evidence_ids", ())):
                    evidence_node = node(
                        "evidence",
                        evidence_id,
                        href=f"/evidence/{quote(evidence_id, safe='')}",
                        context=strategy_context,
                    )
                    edge(evidence_node, candidate_node, "candidate_evidence")
            unresolved.append(
                {
                    "cycle_id": cycle_id,
                    "relation": "campaign_run_experiment_lineage",
                    "reason": "accepted_attestation_does_not_embed_run_local_experiment_identities",
                }
            )
'''
replace_once("src/finagent/visualization/research_workspace.py", old_graph_cycle, new_graph_cycle)

# Evidence app shares configured report roots with accepted-cycle/binding discovery.
replace_once(
    "src/finagent/visualization/workspace_api.py",
    "    research_workspace = ResearchWorkspaceProjection(agent_path)\n",
    '    research_workspace = ResearchWorkspaceProjection(\n        agent_path, cycle_paths=(*report_paths, "configs/research")\n    )\n',
)

# Top-level Workbench composes the new read model from existing projections.
replace_once(
    "src/finagent/visualization/workbench_api.py",
    "from .linked_analytics_acceptance import LinkedAnalyticsAcceptanceProjection\n",
    "from .linked_analytics_acceptance import LinkedAnalyticsAcceptanceProjection\nfrom .linked_strategy_analytics import LinkedStrategyAnalyticsProjection\nfrom .linked_strategy_analytics_routes import attach_linked_strategy_analytics_routes\n",
)
replace_once(
    "src/finagent/visualization/workbench_api.py",
    '''    linked_analytics_acceptance = LinkedAnalyticsAcceptanceProjection(
        strategy_explorer,
        factor_tearsheet,
        portfolio_execution,
    )
''',
    '''    linked_analytics_acceptance = LinkedAnalyticsAcceptanceProjection(
        strategy_explorer,
        factor_tearsheet,
        portfolio_execution,
    )
    linked_strategy_analytics = LinkedStrategyAnalyticsProjection(
        app.state.research_workspace,
        app.state.market_factor_intelligence,
        strategy_explorer,
        portfolio_execution,
        evidence_ids=tuple(item.evidence_id for item in app.state.catalog.items()),
    )
''',
)
replace_once(
    "src/finagent/visualization/workbench_api.py",
    "    app.state.linked_analytics_acceptance = linked_analytics_acceptance\n",
    "    app.state.linked_analytics_acceptance = linked_analytics_acceptance\n    app.state.linked_strategy_analytics = linked_strategy_analytics\n",
)
replace_once(
    "src/finagent/visualization/workbench_api.py",
    "    attach_linked_analytics_acceptance_routes(app, linked_analytics_acceptance)\n",
    "    attach_linked_analytics_acceptance_routes(app, linked_analytics_acceptance)\n    attach_linked_strategy_analytics_routes(app, linked_strategy_analytics)\n",
)
replace_once(
    "src/finagent/visualization/workbench_api.py",
    '            "linked_analytics_acceptance": linked_analytics_acceptance.status(),\n',
    '            "linked_analytics_acceptance": linked_analytics_acceptance.status(),\n            "linked_strategy_analytics": linked_strategy_analytics.status(),\n',
)

# One shared TanStack provider for touched server-state while legacy provider remains for untouched consumers.
replace_once(
    "workspace/src/workbench/shell.tsx",
    'import { NavLink, useLocation } from "react-router-dom";\n',
    'import { QueryClient, QueryClientProvider } from "@tanstack/react-query";\nimport { NavLink, useLocation } from "react-router-dom";\n',
)
old_providers = '''export function WorkbenchProviders({ children }: { children: ReactNode }) {
  return (
    <WorkbenchQueryProvider>
      <WorkbenchContextProvider>
        <ControlPlaneProvider>{children}</ControlPlaneProvider>
      </WorkbenchContextProvider>
    </WorkbenchQueryProvider>
  );
}
'''
new_providers = '''export function WorkbenchProviders({ children }: { children: ReactNode }) {
  const [queryClient] = useState(() => new QueryClient({
    defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false, staleTime: 1_500 } },
  }));
  return (
    <QueryClientProvider client={queryClient}>
      <WorkbenchQueryProvider>
        <WorkbenchContextProvider>
          <ControlPlaneProvider>{children}</ControlPlaneProvider>
        </WorkbenchContextProvider>
      </WorkbenchQueryProvider>
    </QueryClientProvider>
  );
}
'''
replace_once("workspace/src/workbench/shell.tsx", old_providers, new_providers)

# Strategy is an existing canonical WorkbenchContext identity; add an interaction event only.
replace_once(
    "workspace/src/workbench/context.tsx",
    '  | "market_state_selected"\n',
    '  | "market_state_selected"\n  | "strategy_selected"\n',
)

# Panels declare the complete linked identity chain.
replace_once(
    "workspace/src/workbench/panels.ts",
    '{ panel_id: "research-graph", module: "research-graph", title: "Research Graph", route: "/research-graph", status: "available", context_keys: ["project_id", "thread_id", "run_id", "experiment_id", "factor_id", "research_cycle_id", "graph_node_id", "market_state_model_id"], slot: "chart" },',
    '{ panel_id: "research-graph", module: "research-graph", title: "Research Graph", route: "/research-graph", status: "available", context_keys: ["project_id", "thread_id", "run_id", "experiment_id", "factor_id", "research_cycle_id", "graph_node_id", "market_state_model_id", "strategy_id", "portfolio_validation_id"], slot: "chart" },',
)
replace_once(
    "workspace/src/workbench/panels.ts",
    '{ panel_id: "market", module: "market", title: "Market", route: "/market", status: "available", context_keys: ["market_state_model_id", "factor_id", "experiment_id", "run_id"], slot: "chart" },',
    '{ panel_id: "market", module: "market", title: "Market", route: "/market", status: "available", context_keys: ["market_state_model_id", "factor_id", "experiment_id", "run_id", "research_cycle_id", "strategy_id", "portfolio_validation_id"], slot: "chart" },',
)
replace_once(
    "workspace/src/workbench/panels.ts",
    '{ panel_id: "strategy", module: "strategy", title: "Strategy", route: "/strategy", status: "available", context_keys: ["portfolio_validation_id", "asset_id", "date_range", "session_date", "fold_id"], slot: "chart" },',
    '{ panel_id: "strategy", module: "strategy", title: "Strategy", route: "/strategy", status: "available", context_keys: ["research_cycle_id", "strategy_id", "market_state_model_id", "factor_id", "experiment_id", "portfolio_validation_id", "run_id", "asset_id", "date_range", "session_date", "fold_id"], slot: "chart" },',
)
replace_once(
    "workspace/src/workbench/panels.ts",
    '{ panel_id: "portfolio", module: "portfolio", title: "Portfolio", route: "/portfolio", status: "available", context_keys: ["portfolio_validation_id", "date_range", "session_date", "fold_id"], slot: "chart" },',
    '{ panel_id: "portfolio", module: "portfolio", title: "Portfolio", route: "/portfolio", status: "available", context_keys: ["research_cycle_id", "strategy_id", "portfolio_validation_id", "date_range", "session_date", "fold_id"], slot: "chart" },',
)
replace_once(
    "workspace/src/workbench/panels.ts",
    '{ panel_id: "execution", module: "execution", title: "Execution", route: "/execution", status: "available", context_keys: ["portfolio_validation_id", "asset_id", "order_id", "date_range", "session_date", "fold_id"], slot: "chart" },',
    '{ panel_id: "execution", module: "execution", title: "Execution", route: "/execution", status: "available", context_keys: ["research_cycle_id", "strategy_id", "portfolio_validation_id", "asset_id", "order_id", "date_range", "session_date", "fold_id"], slot: "chart" },',
)

# Research Graph understands the canonical Strategy/Portfolio nodes emitted by the server.
replace_once(
    "workspace/src/workbench/researchGraph.tsx",
    "  terminal: 7,\n",
    "  strategy_candidate: 7,\n  strategy: 8,\n  portfolio: 9,\n  execution: 10,\n  agent_run: 6,\n  terminal: 7,\n",
)
replace_once(
    "workspace/src/workbench/researchGraph.tsx",
    '    "market_state_model_id",\n',
    '    "market_state_model_id",\n    "strategy_id",\n    "portfolio_validation_id",\n',
)
replace_once(
    "workspace/src/workbench/researchGraph.tsx",
    '  if (node.kind === "factor" && !output.factor_id) output.factor_id = node.identity;\n',
    '  if (node.kind === "factor" && !output.factor_id) output.factor_id = node.identity;\n  if (node.kind === "strategy_candidate" && !output.strategy_id) output.strategy_id = node.identity;\n  if (node.kind === "portfolio" && !output.portfolio_validation_id) output.portfolio_validation_id = node.identity;\n  if (node.kind === "execution" && !output.portfolio_validation_id) output.portfolio_validation_id = node.identity;\n',
)

# Strategy touched reads migrate to TanStack and gain candidate/no-candidate context without changing V4 calculations.
replace_once(
    "workspace/src/workbench/strategy.tsx",
    'import { useEffect, useMemo } from "react";\n',
    'import { useQuery } from "@tanstack/react-query";\nimport { useEffect, useMemo } from "react";\n',
)
replace_once(
    "workspace/src/workbench/strategy.tsx",
    'import { marketBarApi } from "./marketBars";\nimport { useWorkbenchQuery } from "./query";\n',
    'import { marketBarApi } from "./marketBars";\nimport { LinkedStrategyContextPanel } from "./linkedStrategy";\n',
)
replace_all("workspace/src/workbench/strategy.tsx", "useWorkbenchQuery({", "useQuery({")
replace_all("workspace/src/workbench/strategy.tsx", "key: [", "queryKey: [")
replace_once(
    "workspace/src/workbench/strategy.tsx",
    '<PageHeader eyebrow="V4.2 · Strategy" title="Strategy Decision Explorer" description="No verified V4-0 StrategyDecisionSeries is configured." />\n        <EmptyState',
    '<PageHeader eyebrow="V4.2 · Strategy" title="Strategy Decision Explorer" description="No verified V4-0 StrategyDecisionSeries is configured." />\n        <LinkedStrategyContextPanel />\n        <EmptyState',
)
replace_once(
    "workspace/src/workbench/strategy.tsx",
    '      </PageHeader>\n\n      <div className="strategy-authority-banner">',
    '      </PageHeader>\n\n      <LinkedStrategyContextPanel activeStrategySeriesId={activeSeries.series_id} portfolioValidationId={activeSeries.portfolio_validation_id} />\n\n      <div className="strategy-authority-banner">',
)
replace_once(
    "workspace/src/workbench/strategy.tsx",
    'to={`/factor/${encodeURIComponent(digest)}${workbenchContextSearch(context)}`}',
    'to={`/factors?factor=${encodeURIComponent(digest)}${workbenchContextSearch(context) ? `&${workbenchContextSearch(context).slice(1)}` : ""}`}',
)

# Portfolio/Execution touched reads migrate to TanStack and reuse the same linked context panel.
replace_once(
    "workspace/src/workbench/portfolioExecution.tsx",
    'import { useEffect, useMemo } from "react";\n',
    'import { useQuery } from "@tanstack/react-query";\nimport { useEffect, useMemo } from "react";\n',
)
replace_once(
    "workspace/src/workbench/portfolioExecution.tsx",
    'import { portfolioExecutionApi } from "./portfolioExecutionApi";\n',
    'import { LinkedStrategyContextPanel } from "./linkedStrategy";\nimport { portfolioExecutionApi } from "./portfolioExecutionApi";\n',
)
replace_once(
    "workspace/src/workbench/portfolioExecution.tsx",
    'import { useWorkbenchQuery } from "./query";\n',
    '',
)
replace_all("workspace/src/workbench/portfolioExecution.tsx", "useWorkbenchQuery({", "useQuery({")
replace_all("workspace/src/workbench/portfolioExecution.tsx", "key: [", "queryKey: [")
replace_once(
    "workspace/src/workbench/portfolioExecution.tsx",
    '<PageHeader eyebrow="V4.4 · Linked analytics" title={mode === "portfolio" ? "Portfolio" : "Execution"} description="No A4 validation with a verified V4-0 StrategyDecisionSeries is configured." />\n        <EmptyState',
    '<PageHeader eyebrow="V4.4 · Linked analytics" title={mode === "portfolio" ? "Portfolio" : "Execution"} description="No A4 validation with a verified V4-0 StrategyDecisionSeries is configured." />\n        <LinkedStrategyContextPanel />\n        <EmptyState',
)
replace_once(
    "workspace/src/workbench/portfolioExecution.tsx",
    '<PageHeader eyebrow="V4.4 · Linked analytics" title={mode === "portfolio" ? "Portfolio Interactive Pack" : "Execution Interactive Pack"} description="A4 portfolio authority linked to immutable V4-0 decision evidence." />\n      <div className="v44-card-grid">',
    '<PageHeader eyebrow="V4.4 · Linked analytics" title={mode === "portfolio" ? "Portfolio Interactive Pack" : "Execution Interactive Pack"} description="A4 portfolio authority linked to immutable V4-0 decision evidence." />\n      <LinkedStrategyContextPanel />\n      <div className="v44-card-grid">',
)
replace_once(
    "workspace/src/workbench/portfolioExecution.tsx",
    '      </PageHeader>\n      <div className="v44-authority-banner"><ShieldCheck size={18} /><div><strong>A4 portfolio authority + server-side presentation derivatives</strong>',
    '      </PageHeader>\n      <LinkedStrategyContextPanel activeStrategySeriesId={item.strategy_series_id} portfolioValidationId={validationId} />\n      <div className="v44-authority-banner"><ShieldCheck size={18} /><div><strong>A4 portfolio authority + server-side presentation derivatives</strong>',
)
replace_once(
    "workspace/src/workbench/portfolioExecution.tsx",
    '      </PageHeader>\n      <div className="v44-authority-banner"><ShieldCheck size={18} /><div><strong>V4-0 StrategyDecisionSeries is the execution authority</strong>',
    '      </PageHeader>\n      <LinkedStrategyContextPanel activeStrategySeriesId={item.strategy_series_id} portfolioValidationId={validationId} />\n      <div className="v44-authority-banner"><ShieldCheck size={18} /><div><strong>V4-0 StrategyDecisionSeries is the execution authority</strong>',
)

# Existing Market/Factor/Experiment surfaces get generic Strategy/terminal navigation preserving context; resolution stays server-side.
replace_once(
    "workspace/src/workbench/market.tsx",
    '      <Link to={`/research-graph${search}`}><Activity size={13} /> Research Graph</Link>\n',
    '      <Link to={`/research-graph${search}`}><Activity size={13} /> Research Graph</Link>\n      <Link to={`/strategy${search}`}><Link2 size={12} /> Strategy / terminal</Link>\n',
)
replace_once(
    "workspace/src/workbench/factorIntelligence.tsx",
    '<Link to={`/research-graph${search}`}><GitBranch size={12} /> Research Graph</Link>',
    '<Link to={`/research-graph${search}`}><GitBranch size={12} /> Research Graph</Link><Link to={`/strategy${search}`}><Link2 size={12} /> Strategy / terminal</Link>',
)
replace_once(
    "workspace/src/workbench/experiments.tsx",
    '<Link to={`/research-graph${workbenchContextSearch(context)}`}><GitBranch size={13} /> Research Graph</Link>',
    '<Link to={`/research-graph${workbenchContextSearch(context)}`}><GitBranch size={13} /> Research Graph</Link><Link to={`/strategy${workbenchContextSearch(context)}`}>Strategy / terminal</Link>',
)

# Governance: fourth product slice remains development; human usability is the next gate.
replace_once(
    "docs/status.toml",
    'current_stage_status = "development_in_progress_market_factor_intelligence_slice"',
    'current_stage_status = "development_in_progress_linked_strategy_analytics_slice"',
)
replace_once(
    "docs/status.toml",
    'workbench2_market_factor_intelligence = "third_vertical_slice_in_development"',
    'workbench2_market_factor_intelligence = "third_vertical_slice_in_development"\nworkbench2_linked_strategy_analytics = "fourth_vertical_slice_in_development"',
)
replace_once(
    "docs/development/stages/workbench-2.md",
    'The third vertical slice, `Market State + Factor Intelligence`, is now in Development.',
    'The third vertical slice, `Market State + Factor Intelligence`, is in Development, and the fourth major product slice, `Linked Strategy Analytics`, now links accepted R4 terminal/candidate evidence to existing Strategy/Portfolio/Execution surfaces by explicit canonical identity only.',
)
replace_once(
    "docs/development/stages/workbench-2.md",
    '5. human usability if it is not already included in the earlier slices.',
    '5. real-artifact task-based human usability acceptance after the four major product slices.',
)
replace_once(
    "docs/development/backlog.md",
    'The first Agent Workspace slice, second Experiments/Research Graph slice, and third Market State/Factor Intelligence slice are implementation milestones only; no fresh real-artifact task-based human usability baseline or acceptance has been executed.',
    'The Agent Workspace, Experiments/Research Graph, Market State/Factor Intelligence, and Linked Strategy Analytics product slices are implementation milestones only; no fresh real-artifact task-based human usability baseline or acceptance has been executed.',
)
replace_once(
    "docs/development/backlog.md",
    'Agent Workspace + Experiments/Graph + Market/Factor touched server-state reads now use TanStack Query; list/detail/comparison/graph/cycle and Market/Factor reads use TanStack Query, including SSE-driven graph invalidation. The existing Factor Tear Sheet touched server-state was migrated in the third slice. No new custom-query consumer was added.',
    'Agent Workspace + Experiments/Graph + Market/Factor + touched Strategy/Portfolio/Execution server-state reads now use TanStack Query; the fourth slice migrates existing Strategy/Portfolio/Execution reads without adding a custom-query consumer. Untouched Configuration/other consumers still use the legacy wrapper, so this remains partial progress rather than resolution.',
)

# Workspace CI explicitly covers the new projection/routes/tests; existing checks remain intact.
replace_once(
    ".github/workflows/workspace.yml",
    '      - "tests/test_research_workspace_attempt_hardening_v3.py"\n',
    '      - "tests/test_research_workspace_attempt_hardening_v3.py"\n      - "tests/test_linked_strategy_analytics_v3.py"\n',
)
# Same path list appears in push section too.
replace_once(
    ".github/workflows/workspace.yml",
    '      - "tests/test_research_workspace_attempt_hardening_v3.py"\n      - "pyproject.toml"',
    '      - "tests/test_research_workspace_attempt_hardening_v3.py"\n      - "tests/test_linked_strategy_analytics_v3.py"\n      - "pyproject.toml"',
)
replace_once(
    ".github/workflows/workspace.yml",
    '          tests/test_research_workspace_attempt_hardening_v3.py\n',
    '          tests/test_research_workspace_attempt_hardening_v3.py\n          tests/test_linked_strategy_analytics_v3.py\n',
)
replace_once(
    ".github/workflows/workspace.yml",
    '          src/finagent/visualization/linked_analytics_acceptance_routes.py\n',
    '          src/finagent/visualization/linked_analytics_acceptance_routes.py\n          src/finagent/visualization/linked_strategy_analytics.py\n          src/finagent/visualization/linked_strategy_analytics_routes.py\n',
)
replace_once(
    ".github/workflows/workspace.yml",
    '            src/finagent/visualization/linked_analytics_acceptance_routes.py \\\n',
    '            src/finagent/visualization/linked_analytics_acceptance_routes.py \\\n            src/finagent/visualization/linked_strategy_analytics.py \\\n            src/finagent/visualization/linked_strategy_analytics_routes.py \\\n',
)
replace_once(
    ".github/workflows/workspace.yml",
    '            tests/test_research_workspace_attempt_hardening_v3.py \\\n',
    '            tests/test_research_workspace_attempt_hardening_v3.py \\\n            tests/test_linked_strategy_analytics_v3.py \\\n',
)
replace_once(
    ".github/workflows/workspace.yml",
    '          src/finagent/visualization/linked_analytics_acceptance_routes.py\n      - name: Dependency consistency',
    '          src/finagent/visualization/linked_analytics_acceptance_routes.py\n          src/finagent/visualization/linked_strategy_analytics.py\n          src/finagent/visualization/linked_strategy_analytics_routes.py\n      - name: Dependency consistency',
)

print("linked strategy integration patch applied")
