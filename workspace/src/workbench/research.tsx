import { useState } from "react";
import { controlApi } from "../api";
import { StatusBadge } from "../components";
import { useWorkbenchQuery } from "./query";
import type { ResearchMarketState, ResearchState, ResearchTool } from "./researchTypes";
import "./research.css";

const percent = (value: number | null | undefined) => value == null ? "Unavailable" : `${(value * 100).toFixed(2)}%`;
const titles: Record<string, string> = {
  inspect_market_state: "MarketState inspection", inspect_factor_library: "Factor library inspection",
  inspect_factor: "Factor inspection", propose_factor: "Factor proposal", validate_factor: "Factor validation",
  evaluate_factor: "Factor development evaluation", propose_factor_set: "Factor set proposal",
  propose_allocator: "Allocator proposal", evaluate_portfolio: "Portfolio evaluation",
  compare_experiments: "Experiment comparison", retire_hypothesis: "Lifecycle decision",
  finalize_candidate: "Final candidate decision", record_decision: "Explicit research decision",
  read_literature: "Literature inspection", inspect_experiment_history: "Trial history inspection",
  allocate_budget: "Next evaluation intent", runtime_admission: "Runtime admission",
};

export function ResearchObjective({ onStarted }: { onStarted: (runId: string) => void }) {
  const [objective, setObjective] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [requestId, setRequestId] = useState(() => `research-${crypto.randomUUID()}`);
  const provider = useWorkbenchQuery({ key: ["r4", "provider-status"], queryFn: controlApi.researchStatus });
  const available = provider.data?.provider_available === true;
  async function start() {
    setBusy(true); setMessage("");
    try {
      const response = await controlApi.startResearch({ request_id: requestId, objective: objective.trim() });
      if (response.status >= 400) throw new Error(response.data.provider?.reason ?? "Research start denied");
      setMessage(`Research run ${response.data.state}`);
      setRequestId(`research-${crypto.randomUUID()}`);
      onStarted(response.data.run_id);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Research start failed");
    } finally { setBusy(false); }
  }
  return <section className="research-objective" aria-label="Research objective control">
    <div><strong>Research objective</strong><span className="research-scope">Development only</span></div>
    <label htmlFor="research-objective">Set the research objective</label>
    <textarea id="research-objective" disabled={busy} value={objective} onChange={(e) => { setObjective(e.target.value); setRequestId(`research-${crypto.randomUUID()}`); }} maxLength={1000} rows={2} placeholder="Describe the admitted hypothesis or comparison to investigate." />
    <div className="research-start-row"><button type="button" disabled={!available || !objective.trim() || busy} onClick={() => void start()}>{busy ? "Starting…" : "Start bounded research run"}</button>
      <span role="status">{provider.isPending ? "Checking provider admission…" : available ? `${provider.data?.provider_id} · ${provider.data?.model_id}` : "Provider unavailable / not admitted"}</span></div>
    {message && <p role="status">{message}</p>}
  </section>;
}

function MarketSnapshot({ state }: { state: ResearchMarketState }) {
  return <div className="research-market"><span className="mono">{state.model_id}</span>
    <p>Latest admitted historical state · {state.snapshot.available_at}</p>
    {state.snapshot.probabilities ? <div className="research-probabilities">{state.snapshot.probabilities.map((p, i) => <span key={i}>S{i}: {percent(p)}</span>)}</div> : <p>{state.snapshot.unavailable_reason ?? "State unavailable"}</p>}
  </div>;
}

function RetrospectiveNotice() {
  return <p className="research-retrospective">Tested retrospectively on historical development data. Not historically known / not independent evidence.</p>;
}

export function ResearchToolCard({ tool, status }: { tool: ResearchTool; status: string }) {
  const r = tool.result;
  return <article className={`research-tool-card research-tool-${tool.tool}`} aria-label={titles[tool.tool] ?? tool.tool}>
    <header><strong>{titles[tool.tool] ?? tool.tool}</strong><StatusBadge value={r?.outcome ?? status} tone="neutral" /></header>
    <div className="research-policy"><strong>Policy {tool.policy.outcome}</strong> · {tool.policy.reason.replace(/_/g, " ")}</div>
    {r?.evaluation_mode === "adaptive_development_retrospective" && <RetrospectiveNotice />}
    {r?.admission_semantics && <small>Admission: {r.admission_semantics}</small>}
    {r?.proposal && <div><strong>Proposed now</strong><p>{r.proposal.proposed_at}</p><p className="mono">{r.proposal.factor_id}</p><small>Visible-history cutoff: {r.proposal.history_cutoff ?? "No earlier actions"}</small></div>}
    {r?.market_state && <MarketSnapshot state={r.market_state} />}
    {r?.record?.payload.title && <p><strong>{r.record.payload.title}</strong><br />{r.record.payload.summary}</p>}
    {r?.record?.payload.metrics && <p>Development RankIC: {r.record.payload.metrics.rank_ic?.toFixed(4) ?? "Unavailable"} · {r.record.payload.metrics.valid_count} available observations · {r.status}</p>}
    {r?.attempt_counts && <div><strong>All trial outcomes</strong><ul>{Object.entries(r.attempt_counts).map(([outcome, count]) => <li key={outcome}>{outcome}: {count}</li>)}</ul></div>}
    {r?.total != null && <p>{r.total} records · {r.next_offset != null ? `Next page offset ${r.next_offset}` : "End of admitted page"}</p>}
    {r?.hypothesis_id && tool.tool === "allocate_budget" && <p>Next evaluation intent: {r.hypothesis_id}. Limits remain host-owned.</p>}
    {r?.factor && <p>{r.factor.family} · {r.factor.status}<br />{r.factor.hypothesis}<br /><span className="mono">{r.factor.factor_id}</span></p>}
    {r?.factors && <ul className="research-factor-list">{r.factors.map((f) => <li key={f.factor_id}><strong>{f.family}</strong> · {f.status}<span className="mono">{f.factor_id}</span></li>)}</ul>}
    {r?.factor_set && <div><strong>{r.factor_set.hypothesis_id}</strong><ul className="research-factor-list">{r.factor_set.factor_ids.map((id) => <li className="mono" key={id}>{id}</li>)}</ul></div>}
    {r?.allocator_proposal && <p><strong>{r.allocator_proposal.allocator}</strong> · lookback {r.allocator_proposal.lookback_sessions} sessions · minimum {r.allocator_proposal.minimum_observations} · Ridge α {r.allocator_proposal.ridge_alpha}</p>}
    {r?.summary && <div><p>Preferred allocator: <strong>{r.preferred_allocator}</strong> · all five comparators retained</p>
      <div className="research-table-scroll"><table><caption>5bp development comparison</caption><thead><tr><th>Allocator</th><th>Mean fold</th><th>Worst fold</th><th>Drawdown</th><th>Turnover</th><th>Fallback</th></tr></thead>
        <tbody>{Object.entries(r.summary.arms).map(([name, m]) => <tr key={name}><th>{name}</th><td>{percent(m.mean_fold_return_5bp)}</td><td>{percent(m.worst_fold_return_5bp)}</td><td>{percent(m.drawdown_5bp)}</td><td>{m.turnover_5bp.toFixed(2)}</td><td>{percent(m.fallback_rate)}</td></tr>)}</tbody></table></div>
      <details><summary>Cost sensitivity · 0 / 1 / 5 / 10bp</summary><div className="research-table-scroll"><table><thead><tr><th>Allocator / cost</th><th>Mean fold</th><th>Worst fold</th></tr></thead><tbody>{Object.entries(r.summary.arms).flatMap(([name, m]) => Object.entries(m.cost_sensitivity ?? {}).map(([cost, value]) => <tr key={`${name}-${cost}`}><th>{name} / {cost}bp</th><td>{percent(value.mean_fold_return)}</td><td>{percent(value.worst_fold_return)}</td></tr>))}</tbody></table></div></details>
    </div>}
    {r?.experiments && <div><p>{r.outcome === "NOT_COMPARABLE" ? "Experiments are not comparable; no ranking is provided." : "Compatible source, folds, costs and execution policy."}</p>{r.experiments.map((e) => <p key={e.experiment_id}><span className="mono">{e.experiment_id}</span><br />{e.allocator} · mean fold {percent(e.metrics_5bp?.mean_fold_return_5bp)} · worst fold {percent(e.metrics_5bp?.worst_fold_return_5bp)}</p>)}</div>}
    {tool.tool === "retire_hypothesis" && <p>{String(tool.arguments.factor_id ?? "")} → {String(tool.arguments.status ?? "")}<br />{String(tool.arguments.reason ?? "")}</p>}
    {r?.explicit_decision && <div><p>{r.explicit_decision.critique}</p><strong>Next action</strong><p>{r.explicit_decision.next_action}</p></div>}
    {r?.decision && <p className="research-final-decision">{r.decision}</p>}
    {r?.code && <p>{r.code}</p>}
    {r?.artifact_ref && <p className="research-artifact">Development artifact: <span className="mono">{r.artifact_ref}</span></p>}
    {r?.resource_cost && <p><small>This attempt: {r.resource_cost.evaluation_slots} evaluation slots · {r.resource_cost.tokens} tokens · ${(r.resource_cost.cost_microusd / 1_000_000).toFixed(6)}</small></p>}
    <details className="research-details"><summary>Action details</summary><pre className="json-view">{JSON.stringify({ arguments: tool.arguments, result: r }, null, 2)}</pre></details>
  </article>;
}

export function ResearchContext({ state }: { state: ResearchState }) {
  return <div className="research-context">
    <section className="agent-inspector-block"><h3>Remaining budget</h3><dl className="agent-inspector-grid">
      <div><dt>Tool calls</dt><dd>{state.resources.remaining_tool_calls}</dd></div><div><dt>Evaluations</dt><dd>{state.resources.remaining_evaluations}</dd></div>
      <div><dt>Tokens</dt><dd>{state.resources.remaining_tokens.toLocaleString()}</dd></div><div><dt>Cost</dt><dd>${(state.resources.remaining_cost_microusd / 1_000_000).toFixed(4)}</dd></div>
    </dl></section>
    <section className="agent-inspector-block"><h3>Current factor set</h3>{state.factor_set ? <ul className="research-factor-list">{state.factor_set.factor_ids.map((id) => <li key={id} className="mono">{id}</li>)}</ul> : <p>Not selected</p>}<h3>Preferred allocator</h3><strong>{state.allocator?.allocator ?? "Not selected"}</strong></section>
    <section className="agent-inspector-block"><h3>MarketState</h3>{state.market_state ? <MarketSnapshot state={state.market_state} /> : <p>No state inspected yet</p>}</section>
    <section className="agent-inspector-block"><h3>Latest experiment</h3>{state.latest_experiment ? <div><p className="mono">{state.latest_experiment.experiment_id}</p><p>5bp mean fold: {percent(state.latest_experiment.metrics.mean_fold_return_5bp)}</p><p>Worst fold: {percent(state.latest_experiment.metrics.worst_fold_return_5bp)}</p><RetrospectiveNotice /></div> : <p>No completed portfolio evaluation</p>}</section>
    <section className="agent-inspector-block"><h3>Explicit next decision</h3><p>{state.explicit_decision?.next_action ?? "No next action recorded"}</p><h3>Development candidate</h3><p>{state.candidate?.decision ?? "None proposed"}</p></section>
    <section className="agent-inspector-block"><h3>Authority</h3><p className="research-authority">Development only<br />Alpha: not confirmed<br />PAPER: not accepted<br />Live: not authorized<br />Independent confirmation: false</p></section>
  </div>;
}
