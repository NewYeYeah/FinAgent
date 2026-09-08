import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { Activity, Link2, LockKeyhole } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { EmptyState, ErrorState, LoadingState, PageHeader, Panel, StatusBadge } from "../components";
import { useWorkbenchContext, workbenchContextSearch } from "./context";
import { marketFactorApi, marketFactorQueryKeys } from "./marketFactorApi";
import { researchQueryKeys, researchWorkspaceApi } from "./researchWorkspaceApi";
import "./marketFactor.css";

function json(value: unknown) {
  return value == null ? "unavailable" : JSON.stringify(value, null, 2);
}

function MarketContent() {
  const { context, select } = useWorkbenchContext();
  const indexQuery = useQuery({ queryKey: marketFactorQueryKeys.markets(), queryFn: marketFactorApi.markets, retry: false });
  const cyclesQuery = useQuery({ queryKey: researchQueryKeys.cycles(), queryFn: researchWorkspaceApi.cycles, retry: false });
  const selectedModel = context.market_state_model_id;
  const modelId = selectedModel && indexQuery.data?.items.some((item) => item.model_id === selectedModel)
    ? selectedModel
    : indexQuery.data?.items[0]?.model_id;
  const detailQuery = useQuery({
    queryKey: marketFactorQueryKeys.market(modelId ?? ""),
    queryFn: () => marketFactorApi.market(modelId ?? ""),
    enabled: Boolean(modelId),
    retry: false,
  });

  useEffect(() => {
    if (modelId && context.market_state_model_id !== modelId) {
      select({ market_state_model_id: modelId }, "market_state_selected", { replace: true });
    }
  }, [context.market_state_model_id, modelId, select]);

  if (indexQuery.isPending || cyclesQuery.isPending) return <LoadingState label="Loading persisted MarketState evidence" />;
  if (indexQuery.error || cyclesQuery.error) return <ErrorState error={indexQuery.error ?? cyclesQuery.error} />;

  const accepted = cyclesQuery.data?.items.find((cycle) => cycle.accepted === true);
  const items = indexQuery.data?.items ?? [];
  if (!items.length) {
    return <div className="page market-state-page">
      <PageHeader eyebrow="Workbench-2 · causal state evidence" title="Market State" description="No persisted MarketState model/result is available under the configured Evidence Plane report roots." />
      {accepted ? <div className="market-r4-carry"><strong>{accepted.terminal}</strong><span>AgentValue {accepted.agent_value}</span><span>This accepted completeness/reliability result does not imply MarketState is invalid.</span></div> : null}
      <EmptyState title="MarketState unavailable" detail="The UI does not fit a GMM, cluster, smooth, infer missing states, or fill current state from future observations." />
    </div>;
  }
  if (detailQuery.isPending) return <LoadingState label="Loading MarketState model detail" />;
  if (detailQuery.error) return <ErrorState error={detailQuery.error} />;
  const item = detailQuery.data?.item;
  if (!item) return <EmptyState title="MarketState unavailable" detail="No canonical MarketState model is selected." />;
  const model = item.model as Record<string, unknown>;
  const current = item.current_snapshot;
  const search = workbenchContextSearch(context);

  return <div className="page market-state-page">
    <PageHeader eyebrow="Workbench-2 · causal state evidence" title="Market State" description="Persisted model parameters, causal state probabilities and exact linked research identities. No browser refit or smoothing." />
    {accepted ? <div className="market-r4-carry"><strong>{accepted.terminal}</strong><span>AgentValue {accepted.agent_value}</span><span>{String((accepted.economic_evidence as Record<string, unknown>).complete_deterministic_strategy_count ?? "?")}/{String((accepted.economic_evidence as Record<string, unknown>).deterministic_strategy_count ?? "?")} complete deterministic strategies</span><span>{String((accepted.agent_reliability as Record<string, unknown>).rejected_action_attempts ?? "?")} rejected actions</span></div> : null}
    <div className="market-toolbar"><label><span>Model</span><select value={item.model_id} onChange={(event) => select({ market_state_model_id: event.target.value }, "market_state_selected")}>{items.map((value) => <option value={value.model_id} key={value.model_id}>{value.model_id}</option>)}</select></label><StatusBadge value="causal persisted" tone="positive" /></div>

    <div className="market-factor-grid">
      <Panel title="Model identity & fit window" subtitle="Validated inert JSON parameters; model identity is content-derived in the core.">
        <dl className="market-factor-kv">
          <div><dt>Model</dt><dd className="mono">{item.model_id}</dd></div>
          <div><dt>Version</dt><dd>{String(model.version ?? "unavailable")}</dd></div>
          <div><dt>Estimator</dt><dd>{String(model.estimator ?? "unavailable")}</dd></div>
          <div><dt>Available at</dt><dd>{String(model.available_at ?? "unavailable")}</dd></div>
          <div><dt>Fit / training window</dt><dd><code>{json(model.fit_window)}</code></dd></div>
          <div><dt>Implementation</dt><dd className="mono">{String(model.implementation_id ?? "unavailable")}</dd></div>
        </dl>
      </Panel>
      <Panel title="Latest persisted snapshot" subtitle="Latest by persisted event/availability timestamps; not a realtime or future-filled state.">
        {current ? <dl className="market-factor-kv">
          <div><dt>Event</dt><dd>{String(current.event_time ?? "unavailable")}</dd></div>
          <div><dt>Available at</dt><dd>{String(current.available_at ?? "unavailable")}</dd></div>
          <div><dt>State</dt><dd>{String(current.state ?? "unavailable")}</dd></div>
          <div><dt>Probabilities</dt><dd><code data-testid="market-probabilities">{json(current.probabilities)}</code></dd></div>
          <div><dt>Unavailable reason</dt><dd>{String(current.unavailable_reason ?? "none")}</dd></div>
        </dl> : <div className="market-factor-unavailable">Persisted state history unavailable. No state is inferred.</div>}
      </Panel>
    </div>

    <Panel title="Causal feature/model contract" subtitle="Definitions are persisted; feature identities are unavailable because the artifact does not persist separate canonical feature IDs.">
      <div className="market-feature-list">{item.feature_definitions.length ? item.feature_definitions.map((definition) => <code key={definition}>{definition}</code>) : <span>unavailable</span>}</div>
      <pre className="json-view">{json(item.causal)}</pre>
      <p className="subtle">feature identities: {item.feature_identity_status} · browser_refit=false · smoothing=false · future_fill=false</p>
    </Panel>

    <div className="two-column">
      <Panel title="Historical state probabilities" subtitle="Persisted snapshots only, including unavailable rows and their explicit reasons.">
        <div className="market-history-list">{item.historical_states.length ? item.historical_states.map((row, index) => <article key={`${String(row.event_time)}-${index}`}><time>{String(row.available_at ?? row.event_time)}</time><strong>state {String(row.state ?? "unavailable")}</strong><code>{json(row.probabilities)}</code>{row.unavailable_reason ? <span>{String(row.unavailable_reason)}</span> : null}</article>) : <span className="market-factor-unavailable">unavailable</span>}</div>
      </Panel>
      <Panel title="Observed state transitions" subtitle="Server presentation projection over adjacent available persisted snapshots; gaps reset the chain and no smoothing/rate inference is performed.">
        {item.transitions.length ? <div className="market-transition-list">{item.transitions.map((row, index) => <article key={`${String(row.event_time)}-${index}`}><strong>{String(row.from_state)} → {String(row.to_state)}</strong><time>{String(row.available_at)}</time><small>{String(row.semantics)}</small></article>)}</div> : <div className="market-factor-unavailable">No adjacent persisted state changes are available.</div>}
      </Panel>
    </div>

    <Panel title="Factor performance / allocation by MarketState" subtitle="Factor metrics and allocator weights are copied from persisted FactorLibrary/adaptive portfolio artifacts. Missing bindings remain unavailable.">
      {item.factor_state_evidence.length ? <div className="market-factor-evidence">{item.factor_state_evidence.map((factor) => <article key={factor.factor_id}><header><Link to={`/factors?factor=${encodeURIComponent(factor.factor_id)}${search ? `&${search.slice(1)}` : ""}`} onClick={() => select({ factor_id: factor.factor_id }, "factor_selected")}><Link2 size={12} /> {factor.factor_id}</Link><StatusBadge value={factor.status} tone={factor.status === "REJECTED" || factor.status === "RETIRED" ? "negative" : "neutral"} /></header><pre className="json-view">{json(factor.evaluations.map((value) => ({ evaluation_id: value.evaluation_id, by_market_state: value.by_market_state, conditioning: value.conditioning })))}</pre><small>{factor.allocator_weight_observations.length} persisted allocator weight observations</small></article>)}</div> : <div className="market-factor-unavailable">No FactorLibrary evaluation explicitly binds this model identity.</div>}
    </Panel>

    <div className="market-linked-actions">
      <Link to={`/research-graph${search}`}><Activity size={13} /> Research Graph</Link>
      {item.linked_experiment_ids.map((experimentId) => <Link key={experimentId} to={`/experiments?experiment=${encodeURIComponent(experimentId)}${search ? `&${search.slice(1)}` : ""}`}><Link2 size={12} /> experiment:{experimentId}</Link>)}
    </div>
    <p className="market-authority-note"><LockKeyhole size={12} /> Hidden chain-of-thought is not persisted or projected. Browser financial/statistical recomputation = false.</p>
  </div>;
}

export function MarketStatePage() {
  const [client] = useState(() => new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false, staleTime: 1_500 } } }));
  return <QueryClientProvider client={client}><MarketContent /></QueryClientProvider>;
}
