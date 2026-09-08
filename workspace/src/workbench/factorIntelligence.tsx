import { useQuery } from "@tanstack/react-query";
import { GitBranch, Link2, LockKeyhole } from "lucide-react";
import { Link } from "react-router-dom";

import { ErrorState, LoadingState, StatusBadge } from "../components";
import { useWorkbenchContext, workbenchContextSearch } from "./context";
import { marketFactorApi, marketFactorQueryKeys } from "./marketFactorApi";
import "./marketFactor.css";

function json(value: unknown) {
  return value == null ? "unavailable" : JSON.stringify(value, null, 2);
}

export function FactorIntelligencePanel() {
  const { context, select } = useWorkbenchContext();
  const indexQuery = useQuery({ queryKey: marketFactorQueryKeys.factors(), queryFn: marketFactorApi.factors, retry: false });
  const factorId = context.factor_id && indexQuery.data?.items.some((item) => item.factor_id === context.factor_id)
    ? context.factor_id
    : undefined;
  const detailQuery = useQuery({
    queryKey: marketFactorQueryKeys.factor(factorId ?? ""),
    queryFn: () => marketFactorApi.factor(factorId ?? ""),
    enabled: Boolean(factorId),
    retry: false,
  });

  if (indexQuery.isPending) return <section className="factor-intelligence-shell"><LoadingState label="Loading FactorLibrary intelligence" /></section>;
  if (indexQuery.error) return <section className="factor-intelligence-shell"><ErrorState error={indexQuery.error} /></section>;
  const factors = indexQuery.data?.items ?? [];
  if (!factors.length) return <section className="factor-intelligence-shell"><header><div><span className="eyebrow">Workbench-2 · FactorLibrary</span><h2>Factor Intelligence</h2></div><span className="experiment-contract">no browser recomputation</span></header><div className="market-factor-unavailable">No persisted FactorLibrary is available under the configured report roots. Existing Tear Sheet evidence remains below.</div></section>;

  const detail = detailQuery.data?.item;
  const search = workbenchContextSearch(context);
  return <section className="factor-intelligence-shell" aria-label="Factor Intelligence">
    <header><div><span className="eyebrow">Workbench-2 · FactorLibrary</span><h2>Factor Intelligence</h2><p>Lifecycle, causal state-conditioned development evidence, persisted allocator weights and research lineage.</p></div><span className="experiment-contract">GET-only · server authoritative</span></header>
    <div className="factor-intelligence-selector">{factors.map((factor) => <button type="button" className={factor.factor_id === factorId ? "selected" : ""} key={factor.factor_id} onClick={() => select({ factor_id: factor.factor_id }, "factor_selected")}><strong>{factor.factor_id}</strong><span>{factor.family ?? "family unavailable"}</span><StatusBadge value={factor.status} tone={factor.status === "REJECTED" || factor.status === "RETIRED" ? "negative" : factor.status === "DORMANT" ? "neutral" : "positive"} /></button>)}</div>
    {context.factor_id && !factorId ? <div className="market-factor-unavailable">The selected Tear Sheet factor identity is not present in a persisted FactorLibrary. Intelligence fields remain unavailable rather than inferred.</div> : null}
    {factorId && detailQuery.isPending ? <LoadingState label="Loading persisted factor intelligence" /> : null}
    {detailQuery.error ? <ErrorState error={detailQuery.error} /> : null}
    {detail ? <div className="factor-intelligence-detail">
      <div className="market-factor-grid">
        <article className="factor-intelligence-card"><header><h3>Lifecycle / hypothesis</h3><StatusBadge value={detail.status} tone={detail.status === "REJECTED" || detail.status === "RETIRED" ? "negative" : "neutral"} /></header><dl className="market-factor-kv"><div><dt>Family</dt><dd>{detail.family ?? "unavailable"}</dd></div><div><dt>Mechanism</dt><dd>{detail.mechanism ?? "unavailable"}</dd></div><div><dt>Hypothesis</dt><dd>{detail.hypothesis ?? "unavailable"}</dd></div><div><dt>Origin</dt><dd>{detail.origin ?? "unavailable"}</dd></div></dl><pre className="json-view" data-testid="factor-lifecycle">{json(detail.lifecycle)}</pre></article>
        <article className="factor-intelligence-card"><h3>Provenance / Agent decisions</h3><pre className="json-view" data-testid="factor-provenance">{json(detail.provenance)}</pre>{detail.agent_decision_history.length ? <pre className="json-view">{json(detail.agent_decision_history)}</pre> : <div className="market-factor-unavailable">Agent decision history unavailable for this exact factor identity.</div>}</article>
      </div>
      <div className="market-factor-grid">
        <article className="factor-intelligence-card"><h3>Global development metrics</h3>{detail.global_metrics ? <pre className="json-view" data-testid="factor-global-metrics">{json(detail.global_metrics)}</pre> : <div className="market-factor-unavailable">unavailable · {detail.evaluation_selection_reason}</div>}</article>
        <article className="factor-intelligence-card"><h3>MarketState-conditioned metrics</h3>{detail.state_metrics ? <pre className="json-view" data-testid="factor-state-metrics">{json(detail.state_metrics)}</pre> : <div className="market-factor-unavailable">unavailable</div>}</article>
      </div>
      <div className="market-factor-grid">
        <article className="factor-intelligence-card"><h3>Cost-sensitive economics</h3>{detail.cost_sensitive_economics ? <pre className="json-view">{json(detail.cost_sensitive_economics)}</pre> : <div className="market-factor-unavailable">unavailable</div>}</article>
        <article className="factor-intelligence-card"><h3>Similarity / novelty</h3>{detail.similarity ? <pre className="json-view">{json(detail.similarity)}</pre> : <div className="market-factor-unavailable">similarity unavailable</div>}<p>novelty: {detail.novelty_status}</p></article>
      </div>
      <article className="factor-intelligence-card"><h3>Persisted allocator weight history</h3>{detail.allocator_weights.length ? <div className="factor-weight-list" data-testid="factor-weights">{detail.allocator_weights.map((row, index) => <div key={`${String(row.as_of)}-${String(row.allocator)}-${index}`}><time>{String(row.as_of)}</time><strong>{String(row.allocator)}</strong><code>weight={String(row.weight)}</code><span>{String(row.state_link_status)}</span></div>)}</div> : <div className="market-factor-unavailable">unavailable · no persisted allocator snapshot binds this factor.</div>}</article>
      <article className="factor-intelligence-card"><h3>Canonical linked research</h3><div className="market-linked-actions">{detail.linked_market_state_model_ids.map((modelId) => <Link key={modelId} to={`/market?market_model=${encodeURIComponent(modelId)}${search ? `&${search.slice(1)}` : ""}`} onClick={() => select({ market_state_model_id: modelId }, "market_state_selected")}><Link2 size={12} /> MarketState:{modelId}</Link>)}{detail.linked_experiments.map((experiment) => <Link key={String(experiment.identity)} to={`/experiments?experiment=${encodeURIComponent(String(experiment.identity))}${search ? `&${search.slice(1)}` : ""}`}><Link2 size={12} /> experiment:{String(experiment.identity)}</Link>)}<Link to={`/research-graph${search}`}><GitBranch size={12} /> Research Graph</Link>{detail.agent_decision_history.map((decision) => decision.run_id ? <Link key={String(decision.node_id)} to={`/agent?run=${encodeURIComponent(String(decision.run_id))}${search ? `&${search.slice(1)}` : ""}`}>Agent run:{String(decision.run_id)}</Link> : null)}</div><pre className="json-view">{json(detail.evidence_identities)}</pre></article>
    </div> : null}
    <p className="market-authority-note"><LockKeyhole size={12} /> Existing Tear Sheet IC/decay/heatmap/bootstrap/multiplicity/correlation/provenance remains authoritative below. Hidden chain-of-thought is not persisted or projected.</p>
  </section>;
}
