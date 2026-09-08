import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { FlaskConical, Link2, LockKeyhole, Scale } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { ErrorState, LoadingState, StatusBadge } from "../components";
import { useWorkbenchContext, workbenchContextSearch } from "./context";
import {
  researchQueryKeys,
  researchWorkspaceApi,
  type ResearchExperiment,
} from "./researchWorkspaceApi";
import { WorkbenchInspectorSlot } from "./shell";
import "./experiments.css";

function formatMicrousd(value?: number | null) {
  return value == null ? "unavailable" : `${value} µUSD`;
}

function identity(value?: string | null) {
  return value?.trim() || "unavailable";
}

function ExperimentList({
  items,
  selected,
  compared,
  onSelect,
  onCompare,
}: {
  items: ResearchExperiment[];
  selected?: string;
  compared: Set<string>;
  onSelect: (item: ResearchExperiment) => void;
  onCompare: (item: ResearchExperiment, checked: boolean) => void;
}) {
  if (!items.length) {
    return <div className="experiment-empty">No persisted experiment attempt is available for this selection. No experiment identity is fabricated.</div>;
  }
  return <div className="experiment-list">{items.map((item) => <article className={`experiment-row ${selected === item.identity ? "selected" : ""}`} key={item.attempt_id}>
    <button type="button" onClick={() => onSelect(item)}>
      <div><strong>{item.experiment_id ?? `attempt:${item.attempt_id}`}</strong><span className="mono">{item.run_id}</span></div>
      <StatusBadge value={item.status} tone={item.status === "completed" ? "positive" : item.status === "failed" || item.status === "rejected" ? "negative" : "neutral"} />
      <small>{item.objective}</small>
      <small>{identity(item.allocator)} · {identity(item.factor_set_id)}</small>
      {item.error ? <small className="experiment-negative-detail">{item.error}</small> : null}
    </button>
    <label className="experiment-compare-toggle">
      <input
        type="checkbox"
        disabled={!item.experiment_id}
        checked={Boolean(item.experiment_id && compared.has(item.experiment_id))}
        onChange={(event) => onCompare(item, event.currentTarget.checked)}
      /> compare
    </label>
  </article>)}</div>;
}

function MetricProjection({ item }: { item: ResearchExperiment }) {
  return <section className="experiment-card">
    <header><h3>Authoritative result</h3><span className="experiment-contract">no browser recomputation</span></header>
    {item.authoritative_metrics ? <pre className="json-view" data-testid="authoritative-metrics">{JSON.stringify(item.authoritative_metrics, null, 2)}</pre> : <div className="experiment-empty">Authoritative metrics are unavailable/incomplete for this persisted attempt.</div>}
    <dl className="experiment-kv">
      <div><dt>Metrics source</dt><dd>{item.metrics_source}</dd></div>
      <div><dt>Evaluation scope</dt><dd><code>{JSON.stringify(item.evaluation_scope)}</code></dd></div>
      <div><dt>Outcome</dt><dd>{identity(item.outcome)}</dd></div>
      <div><dt>Error / rejection</dt><dd>{identity(item.error)}</dd></div>
    </dl>
  </section>;
}

function ExperimentDetail({ item }: { item: ResearchExperiment }) {
  const { context } = useWorkbenchContext();
  const search = workbenchContextSearch(context);
  return <div className="experiment-detail">
    <section className="experiment-card experiment-objective">
      <span className="eyebrow">Experiment / trial identity</span>
      <h2>{item.experiment_id ?? item.attempt_id}</h2>
      <p>{item.objective}</p>
      <dl className="experiment-kv">
        <div><dt>Identity kind</dt><dd>{item.identity_kind}</dd></div>
        <div><dt>Hypothesis</dt><dd className="mono">{identity(item.hypothesis_id)}</dd></div>
        <div><dt>Factor set</dt><dd className="mono">{identity(item.factor_set_id)}</dd></div>
        <div><dt>Allocator</dt><dd>{identity(item.allocator)} <span className="mono">{identity(item.allocator_proposal_id)}</span></dd></div>
      </dl>
    </section>
    <MetricProjection item={item} />
    <section className="experiment-card">
      <h3>Provider / model / resource accounting</h3>
      <dl className="experiment-kv">
        <div><dt>Provider</dt><dd className="mono">{item.provider_id}</dd></div>
        <div><dt>Model</dt><dd className="mono">{item.model_id}</dd></div>
        <div><dt>Tokens</dt><dd>{item.tokens ?? "unavailable"}</dd></div>
        <div><dt>Cost</dt><dd>{formatMicrousd(item.cost_microusd)}</dd></div>
        <div><dt>Evaluation used</dt><dd>{item.evaluation_budget.used ?? "unavailable"}</dd></div>
        <div><dt>Evaluation remaining</dt><dd>{item.evaluation_budget.remaining ?? "unavailable"}</dd></div>
      </dl>
      <small>Accounting is the persisted research resource snapshot associated with the trial result; it is not recalculated in React.</small>
    </section>
    <section className="experiment-card">
      <h3>Agent final decision</h3>
      {item.agent_decision ? <dl className="experiment-kv">
        <div><dt>Decision action</dt><dd className="mono">{item.agent_decision.action_id}</dd></div>
        <div><dt>Recommendation</dt><dd>{item.agent_decision.recommendation}</dd></div>
        <div><dt>Decision</dt><dd>{identity(item.agent_decision.decision)}</dd></div>
        <div><dt>Terminal</dt><dd>{identity(item.agent_decision.terminal)}</dd></div>
      </dl> : <div className="experiment-empty">No persisted keep/modify/reject decision explicitly references this experiment.</div>}
    </section>
    <section className="experiment-card">
      <h3>Related canonical identities</h3>
      <div className="experiment-links">
        {item.factor_ids.map((factorId) => <Link key={factorId} to={`/factors?factor=${encodeURIComponent(factorId)}${search ? `&${search.slice(1)}` : ""}`}><Link2 size={12} /> factor:{factorId}</Link>)}
        {item.related_identities.map((related) => <Link key={related} to={`/ref/evidence/${encodeURIComponent(related)}${search}`}><Link2 size={12} /> {related}</Link>)}
        <Link to={`/agent?run=${encodeURIComponent(item.run_id)}`}><Link2 size={12} /> Agent run</Link>
      </div>
    </section>
  </div>;
}

function ComparisonPanel({ ids }: { ids: string[] }) {
  const query = useQuery({
    queryKey: researchQueryKeys.comparison(ids),
    queryFn: () => researchWorkspaceApi.comparison(ids),
    enabled: ids.length >= 2,
    retry: false,
  });
  if (ids.length < 2) return <section className="experiment-card comparison-panel"><Scale size={16} /><p>Select at least two persisted experiment identities for direct comparison.</p></section>;
  if (query.isPending) return <LoadingState label="Loading persisted experiment comparison" />;
  if (query.error) return <ErrorState error={query.error} />;
  const comparison = query.data;
  if (!comparison) return null;
  return <section className="experiment-card comparison-panel" data-testid="experiment-comparison">
    <header><h3>Persisted comparison</h3><StatusBadge value={comparison.comparable ? "comparable" : "not comparable"} tone={comparison.comparable ? "positive" : "negative"} /></header>
    {comparison.comparable ? <pre className="json-view">{JSON.stringify(comparison.persisted_comparison, null, 2)}</pre> : <div className="experiment-empty">Comparison unavailable: <strong>{comparison.reason}</strong>. The browser does not rank or synthesize a replacement comparison.</div>}
    <small>ranking = null · browser_recomputation = false · comparison call {comparison.comparison_call_id ?? "unavailable"}</small>
  </section>;
}

function ExperimentsContent() {
  const { context, select } = useWorkbenchContext();
  const runId = context.run_id ?? "";
  const selectedIdentity = context.experiment_id;
  const compared = useMemo(() => new Set((context.comparison_ids ?? "").split(",").map((value) => value.trim()).filter(Boolean)), [context.comparison_ids]);
  const listQuery = useQuery({ queryKey: researchQueryKeys.experiments(runId), queryFn: () => researchWorkspaceApi.experiments(runId || undefined), retry: false });
  const cyclesQuery = useQuery({ queryKey: researchQueryKeys.cycles(), queryFn: researchWorkspaceApi.cycles, retry: false });
  const detailQuery = useQuery({ queryKey: researchQueryKeys.experiment(selectedIdentity ?? ""), queryFn: () => researchWorkspaceApi.experiment(selectedIdentity ?? ""), enabled: Boolean(selectedIdentity), retry: false });

  if (listQuery.isPending || cyclesQuery.isPending) return <LoadingState label="Loading persisted research experiments" />;
  if (listQuery.error || cyclesQuery.error) return <ErrorState error={listQuery.error ?? cyclesQuery.error} />;
  const items = listQuery.data?.items ?? [];
  const selected = detailQuery.data?.item;
  const selectedIds = [...compared];
  const accepted = cyclesQuery.data?.items.find((cycle) => cycle.terminal === "NO_ADAPTIVE_CANDIDATE") ?? cyclesQuery.data?.items[0];

  return <div className="experiments-page">
    <header className="experiments-header"><div><span className="eyebrow">Workbench-2 · persisted trials</span><h1>Experiments</h1><p>Directly inspect and compare persisted R4 trial/evaluation results. React selects and renders; it does not calculate RankIC, PnL, allocator results or rankings.</p></div><div className="experiment-contract-stack"><span>GET-only</span><span>server projection authoritative</span><span>hidden reasoning excluded</span></div></header>
    {accepted ? <section className="experiment-terminal-line"><strong>{accepted.terminal}</strong><span>AgentValue {accepted.agent_value}</span><span>{String(accepted.economic_evidence.complete_deterministic_strategy_count ?? "?")}/{String(accepted.economic_evidence.deterministic_strategy_count ?? "?")} complete deterministic strategies</span><span>{String(accepted.agent_reliability.rejected_action_attempts ?? "?")} rejected actions</span></section> : null}
    <div className="experiments-grid">
      <aside className="experiments-index"><header><FlaskConical size={16} /><strong>Persisted attempts</strong><span>{items.length}</span></header><ExperimentList items={items} selected={selectedIdentity} compared={compared} onSelect={(item) => select({ project_id: item.project_id || null, thread_id: item.thread_id || null, run_id: item.run_id, experiment_id: item.identity }, "experiment_selected")} onCompare={(item, checked) => {
        if (!item.experiment_id) return;
        const next = new Set(compared);
        if (checked) next.add(item.experiment_id); else next.delete(item.experiment_id);
        select({ comparison_ids: [...next].join(",") || null }, "experiment_selected");
      }} /></aside>
      <main>{selectedIdentity && detailQuery.isPending ? <LoadingState label="Loading experiment detail" /> : detailQuery.error ? <ErrorState error={detailQuery.error} /> : selected ? <ExperimentDetail item={selected} /> : <div className="experiment-empty experiment-detail-empty">Select an experiment or failed/rejected attempt. Empty and incomplete evidence remain explicit.</div>}
        <ComparisonPanel ids={selectedIds} />
      </main>
      <WorkbenchInspectorSlot title="Experiment authority"><div className="experiment-inspector"><h3>Selection</h3><p className="mono">{selectedIdentity ?? "none"}</p><h3>Comparison</h3><p>{selectedIds.length ? selectedIds.join(" · ") : "none"}</p><Link to={`/research-graph${workbenchContextSearch(context)}`}>Open Research Graph</Link><p><LockKeyhole size={12} /> Hidden chain-of-thought is not persisted or projected.</p><p>Missing experiment IDs, metrics, model/provider identity or lineage stay unavailable; the UI does not infer them.</p></div></WorkbenchInspectorSlot>
    </div>
  </div>;
}

export function ExperimentsPage() {
  const [client] = useState(() => new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false, staleTime: 1_500 } } }));
  return <QueryClientProvider client={client}><ExperimentsContent /></QueryClientProvider>;
}
