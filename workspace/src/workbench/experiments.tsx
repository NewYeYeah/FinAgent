import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { FlaskConical, Link2, LockKeyhole, Scale } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { ErrorState, LoadingState, StatusBadge } from "../components";
import { PersistedTerminalLabel, useWorkbenchI18n } from "../i18n";
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

function ExperimentList({ items, selected, compared, onSelect, onCompare }: {
  items: ResearchExperiment[];
  selected?: string;
  compared: Set<string>;
  onSelect: (item: ResearchExperiment) => void;
  onCompare: (item: ResearchExperiment, checked: boolean) => void;
}) {
  const { t } = useWorkbenchI18n();
  if (!items.length) return <div className="experiment-empty">{t("No persisted experiment attempt is available for this selection. No experiment identity is fabricated.")}</div>;
  return <div className="experiment-list">{items.map((item) => <article className={`experiment-row ${selected === item.identity ? "selected" : ""}`} key={item.attempt_id}>
    <button type="button" onClick={() => onSelect(item)}>
      <div><strong>{item.experiment_id ?? `attempt:${item.attempt_id}`}</strong><span className="mono">{item.run_id}</span></div>
      <StatusBadge value={item.status} tone={item.status === "completed" ? "positive" : item.status === "failed" || item.status === "rejected" ? "negative" : "neutral"} />
      <small>{item.objective}</small>
      <small>{identity(item.allocator)} · {identity(item.factor_set_id)}</small>
      {item.error ? <small className="experiment-negative-detail">{item.error}</small> : null}
    </button>
    <label className="experiment-compare-toggle"><input type="checkbox" disabled={!item.experiment_id} checked={Boolean(item.experiment_id && compared.has(item.experiment_id))} onChange={(event) => onCompare(item, event.currentTarget.checked)} /> {t("compare")}</label>
  </article>)}</div>;
}

function MetricProjection({ item }: { item: ResearchExperiment }) {
  const { t } = useWorkbenchI18n();
  return <section className="experiment-card">
    <header><h3>{t("Authoritative result")}</h3><span className="experiment-contract">{t("no browser recomputation")}</span></header>
    {item.authoritative_metrics ? <pre className="json-view" data-testid="authoritative-metrics">{JSON.stringify(item.authoritative_metrics, null, 2)}</pre> : <div className="experiment-empty">{t("Authoritative metrics are unavailable/incomplete for this persisted attempt.")}</div>}
    <dl className="experiment-kv">
      <div><dt>{t("Metrics source")}</dt><dd>{item.metrics_source}</dd></div>
      <div><dt>{t("Evaluation scope")}</dt><dd><code>{JSON.stringify(item.evaluation_scope)}</code></dd></div>
      <div><dt>{t("Outcome")}</dt><dd>{identity(item.outcome)}</dd></div>
      <div><dt>{t("Error / rejection")}</dt><dd>{identity(item.error)}</dd></div>
    </dl>
  </section>;
}

function ExperimentDetail({ item }: { item: ResearchExperiment }) {
  const { context } = useWorkbenchContext();
  const { t } = useWorkbenchI18n();
  const search = workbenchContextSearch(context);
  return <div className="experiment-detail">
    <section className="experiment-card experiment-objective">
      <span className="eyebrow">{t("Experiment / trial identity")}</span><h2>{item.experiment_id ?? item.attempt_id}</h2><p>{item.objective}</p>
      <dl className="experiment-kv"><div><dt>{t("Identity kind")}</dt><dd>{item.identity_kind}</dd></div><div><dt>{t("Hypothesis")}</dt><dd className="mono">{identity(item.hypothesis_id)}</dd></div><div><dt>{t("Factor set")}</dt><dd className="mono">{identity(item.factor_set_id)}</dd></div><div><dt>{t("Allocator")}</dt><dd>{identity(item.allocator)} <span className="mono">{identity(item.allocator_proposal_id)}</span></dd></div></dl>
    </section>
    <MetricProjection item={item} />
    <section className="experiment-card"><h3>{t("Provider / model / resource accounting")}</h3><dl className="experiment-kv">
      <div><dt>{t("Provider")}</dt><dd className="mono">{item.provider_id}</dd></div><div><dt>{t("Model")}</dt><dd className="mono">{item.model_id}</dd></div><div><dt>{t("Tokens")}</dt><dd>{item.tokens ?? "unavailable"}</dd></div><div><dt>{t("Cost")}</dt><dd>{formatMicrousd(item.cost_microusd)}</dd></div><div><dt>{t("Evaluation used")}</dt><dd>{item.evaluation_budget.used ?? "unavailable"}</dd></div><div><dt>{t("Evaluation remaining")}</dt><dd>{item.evaluation_budget.remaining ?? "unavailable"}</dd></div>
    </dl><small>Accounting is the persisted research resource snapshot associated with the trial result; it is not recalculated in React.</small></section>
    <section className="experiment-card"><h3>{t("Agent final decision")}</h3>{item.agent_decision ? <dl className="experiment-kv"><div><dt>{t("Decision action")}</dt><dd className="mono">{item.agent_decision.action_id}</dd></div><div><dt>{t("Recommendation")}</dt><dd>{item.agent_decision.recommendation}</dd></div><div><dt>{t("Decision")}</dt><dd>{identity(item.agent_decision.decision)}</dd></div><div><dt>{t("Terminal")}</dt><dd>{identity(item.agent_decision.terminal)}</dd></div></dl> : <div className="experiment-empty">{t("No persisted keep/modify/reject decision explicitly references this experiment.")}</div>}</section>
    <section className="experiment-card"><h3>{t("Related canonical identities")}</h3><div className="experiment-links">{item.factor_ids.map((factorId) => <Link key={factorId} to={`/factors?factor=${encodeURIComponent(factorId)}${search ? `&${search.slice(1)}` : ""}`}><Link2 size={12} /> factor:{factorId}</Link>)}{item.related_identities.map((related) => <Link key={related} to={`/ref/evidence/${encodeURIComponent(related)}${search}`}><Link2 size={12} /> {related}</Link>)}<Link to={`/agent?run=${encodeURIComponent(item.run_id)}`}><Link2 size={12} /> {t("Agent run")}</Link></div></section>
  </div>;
}

function ComparisonPanel({ ids }: { ids: string[] }) {
  const { t } = useWorkbenchI18n();
  const query = useQuery({ queryKey: researchQueryKeys.comparison(ids), queryFn: () => researchWorkspaceApi.comparison(ids), enabled: ids.length >= 2, retry: false });
  if (ids.length < 2) return <section className="experiment-card comparison-panel"><Scale size={16} /><p>{t("Select at least two persisted experiment identities for direct comparison.")}</p></section>;
  if (query.isPending) return <LoadingState label="Loading persisted experiment comparison" />;
  if (query.error) return <ErrorState error={query.error} />;
  const comparison = query.data;
  if (!comparison) return null;
  return <section className="experiment-card comparison-panel" data-testid="experiment-comparison">
    <header><h3>{t("Persisted comparison")}</h3><StatusBadge value={comparison.comparable ? "comparable" : "not comparable"} tone={comparison.comparable ? "positive" : "negative"} /></header>
    {comparison.comparable ? <pre className="json-view">{JSON.stringify(comparison.persisted_comparison, null, 2)}</pre> : <div className="experiment-empty">{t("Comparison unavailable")}: <strong>{comparison.reason}</strong>. The browser does not rank or synthesize a replacement comparison.</div>}
    <small>ranking = null · browser_recomputation = false · comparison call {comparison.comparison_call_id ?? "unavailable"}</small>
  </section>;
}

function ExperimentsContent() {
  const { context, select } = useWorkbenchContext();
  const { t } = useWorkbenchI18n();
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
  const accepted = cyclesQuery.data?.items.find((cycle) => cycle.accepted === true && cycle.terminal === "NO_ADAPTIVE_CANDIDATE");
  return <div className="experiments-page">
    <header className="experiments-header"><div><span className="eyebrow">{t("Workbench-2 · persisted trials")}</span><h1>{t("Experiments")}</h1><p>{t("Directly inspect and compare persisted R4 trial/evaluation results. React selects and renders; it does not calculate RankIC, PnL, allocator results or rankings.")}</p></div><div className="experiment-contract-stack"><span>{t("GET-only")}</span><span>{t("server projection authoritative")}</span><span>{t("hidden reasoning excluded")}</span></div></header>
    {accepted ? <section className="experiment-terminal-line"><strong><PersistedTerminalLabel value={accepted.terminal ?? "NO_ADAPTIVE_CANDIDATE"} /></strong><span>AgentValue <code>{accepted.agent_value}</code></span><span>{String(accepted.economic_evidence.complete_deterministic_strategy_count ?? "?")}/{String(accepted.economic_evidence.deterministic_strategy_count ?? "?")} {t("complete deterministic strategies")}</span><span>{String(accepted.agent_reliability.rejected_action_attempts ?? "?")} {t("rejected actions")}</span></section> : null}
    <div className="experiments-grid"><aside className="experiments-index"><header><FlaskConical size={16} /><strong>{t("Persisted attempts")}</strong><span>{items.length}</span></header><ExperimentList items={items} selected={selectedIdentity} compared={compared} onSelect={(item) => select({ project_id: item.project_id || null, thread_id: item.thread_id || null, run_id: item.run_id, experiment_id: item.identity }, "experiment_selected")} onCompare={(item, checked) => { if (!item.experiment_id) return; const next = new Set(compared); if (checked) next.add(item.experiment_id); else next.delete(item.experiment_id); select({ comparison_ids: [...next].join(",") || null }, "experiment_selected"); }} /></aside>
      <main>{selectedIdentity && detailQuery.isPending ? <LoadingState label="Loading experiment detail" /> : detailQuery.error ? <ErrorState error={detailQuery.error} /> : selected ? <ExperimentDetail item={selected} /> : <div className="experiment-empty experiment-detail-empty">{t("Select an experiment or failed/rejected attempt. Empty and incomplete evidence remain explicit.")}</div>}<ComparisonPanel ids={selectedIds} /></main>
      <WorkbenchInspectorSlot title="Experiment authority"><div className="experiment-inspector"><h3>{t("Selection")}</h3><p className="mono">{selectedIdentity ?? "none"}</p><h3>{t("Comparison")}</h3><p>{selectedIds.length ? selectedIds.join(" · ") : "none"}</p><Link to={`/research-graph${workbenchContextSearch(context)}`}>{t("Open Research Graph")}</Link><Link to={`/strategy${workbenchContextSearch(context)}`}>{t("Strategy / terminal")}</Link><p><LockKeyhole size={12} /> Hidden chain-of-thought is not persisted or projected.</p><p>Missing experiment IDs, metrics, model/provider identity or lineage stay unavailable; the UI does not infer them.</p></div></WorkbenchInspectorSlot>
    </div>
  </div>;
}

export function ExperimentsPage() {
  const [client] = useState(() => new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false, staleTime: 1_500 } } }));
  return <QueryClientProvider client={client}><ExperimentsContent /></QueryClientProvider>;
}
