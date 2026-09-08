import { useQuery } from "@tanstack/react-query";
import { Activity, ArrowRight, FlaskConical, GitBranch, Link2, LockKeyhole } from "lucide-react";
import { useEffect } from "react";
import { Link } from "react-router-dom";

import { ErrorState, LoadingState, StatusBadge } from "../components";
import { PersistedTerminalLabel, useWorkbenchI18n } from "../i18n";
import { useWorkbenchContext } from "./context";
import { linkedStrategyApi, linkedStrategyQueryKeys } from "./linkedStrategyApi";
import "./linkedStrategy.css";

function count(value: unknown): string { return value == null ? "unavailable" : String(value); }

export function LinkedStrategyContextPanel({ activeStrategySeriesId, portfolioValidationId }: { activeStrategySeriesId?: string; portfolioValidationId?: string }) {
  const { context, select } = useWorkbenchContext();
  const { t } = useWorkbenchI18n();
  const indexQuery = useQuery({ queryKey: linkedStrategyQueryKeys.index(), queryFn: linkedStrategyApi.index, retry: false });
  const cycleId = context.research_cycle_id ?? indexQuery.data?.default_cycle_id ?? "";
  const cycleQuery = useQuery({ queryKey: linkedStrategyQueryKeys.cycle(cycleId), queryFn: () => linkedStrategyApi.cycle(cycleId), enabled: Boolean(cycleId), retry: false });

  useEffect(() => { if (!cycleId || context.research_cycle_id === cycleId) return; select({ research_cycle_id: cycleId }, "strategy_selected", { replace: true }); }, [context.research_cycle_id, cycleId, select]);
  useEffect(() => { const candidate = cycleQuery.data?.cycle.candidate_id; if (!candidate || context.strategy_id === candidate) return; select({ strategy_id: candidate }, "strategy_selected", { replace: true }); }, [context.strategy_id, cycleQuery.data?.cycle.candidate_id, select]);

  if (indexQuery.isPending || (cycleId && cycleQuery.isPending)) return <section className="linked-strategy-panel" aria-label={t("Linked strategy analytics")}><LoadingState label="Loading linked research/strategy evidence" /></section>;
  if (indexQuery.error || cycleQuery.error) return <section className="linked-strategy-panel" aria-label={t("Linked strategy analytics")}><ErrorState error={indexQuery.error ?? cycleQuery.error} /></section>;
  if (!cycleId || !cycleQuery.data) return <section className="linked-strategy-panel" aria-label={t("Linked strategy analytics")} data-testid="linked-strategy-panel"><header><div><span>{t("Workbench-2 · linked strategy analytics")}</span><strong>{t("No accepted R4 cycle is uniquely selected")}</strong></div><StatusBadge value="unresolved" tone="neutral" /></header><p>No candidate/terminal relationship is guessed. Select a canonical research cycle to inspect its strategy evidence.</p></section>;

  const detail = cycleQuery.data;
  const economic = detail.cycle.economic_evidence;
  const reliability = detail.cycle.agent_reliability;
  const binding = detail.strategy_binding.binding ?? {};
  const boundSeries = String(binding.strategy_series_id ?? "");
  const boundPortfolio = String(binding.portfolio_validation_id ?? "");
  const activeBound = Boolean(activeStrategySeriesId && boundSeries === activeStrategySeriesId);
  const portfolioBound = Boolean(portfolioValidationId && boundPortfolio === portfolioValidationId);

  if (detail.mode === "no_candidate") {
    const terminal = detail.cycle.terminal ?? "NO_ADAPTIVE_CANDIDATE";
    return <section className="linked-strategy-panel no-candidate" aria-label={t("Linked strategy analytics")} data-testid="linked-strategy-panel">
      <header><div><span>{t("Accepted R4 terminal")}</span><strong><PersistedTerminalLabel value={terminal} /></strong></div><StatusBadge value="no candidate" tone="neutral" /></header>
      <div className="linked-strategy-facts"><span>AgentValue <b>{detail.cycle.agent_value ?? "unavailable"}</b></span><span>{count(economic.complete_deterministic_strategy_count)}/{count(economic.deterministic_strategy_count)} {t("complete deterministic strategies")}</span><span>{count(reliability.rejected_action_attempts)} {t("rejected Agent actions")}</span><span>R5 <b>{detail.r5.status}</b></span></div>
      <p>{t(String(detail.explanation.basis ?? "Accepted completeness/reliability evidence does not contain an AdaptiveStrategy candidate."))}</p>
      <p className="linked-strategy-boundary">Historical StrategyDecisionSeries/A4 evidence may still be inspectable, but it is <strong>not bound to this R4 terminal</strong>. {t("This does not mean all strategies lost money, MarketState failed, or Agent value was proven negative.")}</p>
      <div className="linked-strategy-evidence-list"><span>{detail.available_evidence.market_state_model_ids.length} persisted MarketState model(s)</span><span>{detail.available_evidence.factors.length} persisted FactorLibrary factor(s)</span><span>{detail.available_evidence.canonical_experiment_ids.length} canonical experiment(s) visible in the current audit</span><span>{detail.available_evidence.historical_strategy_series.length} historical strategy evidence series, unbound unless explicitly referenced</span></div>
      <div className="linked-strategy-links">{detail.links.research_graph ? <Link to={detail.links.research_graph}><GitBranch size={13} /> {t("Research Graph")}</Link> : null}<Link to={`/experiments?cycle=${encodeURIComponent(detail.cycle.cycle_id)}`}><FlaskConical size={13} /> {t("Experiments")}</Link></div>
      <small><LockKeyhole size={12} /> Hidden chain-of-thought is not persisted or projected. Browser financial/statistical recomputation = false.</small>
    </section>;
  }

  return <section className="linked-strategy-panel candidate" aria-label={t("Linked strategy analytics")} data-testid="linked-strategy-panel">
    <header><div><span>{t("Persisted R4 development candidate")}</span><strong>{detail.cycle.candidate_id ?? "candidate identity unavailable"}</strong></div><StatusBadge value={detail.strategy_binding.status} tone={detail.strategy_binding.status === "resolved" ? "positive" : "neutral"} /></header>
    <div className="linked-strategy-facts"><span>{t("Terminal")} <b>{detail.cycle.terminal ?? "candidate"}</b></span><span>R5 <b>{detail.r5.status}</b></span><span>{t("Strategy evidence")} <b>{detail.combined_strategy_evidence.available ? "persisted" : "unavailable"}</b></span><span>{t("Portfolio / execution")} <b>{detail.target_portfolio.available && detail.execution_pnl.available ? "persisted" : "unavailable"}</b></span></div>
    {activeStrategySeriesId ? <p className="linked-strategy-boundary">Current StrategyDecisionSeries: <code>{activeStrategySeriesId}</code> · {activeBound ? "explicitly bound to this candidate" : "not claimed as this candidate"}.</p> : null}
    {portfolioValidationId ? <p className="linked-strategy-boundary">Current A4 portfolio: <code>{portfolioValidationId}</code> · {portfolioBound ? "explicitly bound to this candidate" : "not claimed as this candidate"}.</p> : null}
    <div className="linked-strategy-links">{detail.links.market ? <Link to={detail.links.market}><Activity size={13} /> {t("Market State")}</Link> : null}{(detail.links.factors ?? []).map((href, index) => <Link key={href} to={href}><Link2 size={12} /> {t("Factor")} {index + 1}</Link>)}{(detail.links.experiments ?? []).map((href, index) => <Link key={href} to={href}><FlaskConical size={12} /> {t("Experiment")} {index + 1}</Link>)}{detail.links.strategy ? <Link to={detail.links.strategy}>{t("Strategy evidence")} <ArrowRight size={12} /></Link> : null}{detail.links.portfolio ? <Link to={detail.links.portfolio}>{t("Portfolio")} <ArrowRight size={12} /></Link> : null}{detail.links.execution ? <Link to={detail.links.execution}>{t("Execution / PnL")} <ArrowRight size={12} /></Link> : null}{detail.links.research_graph ? <Link to={detail.links.research_graph}><GitBranch size={13} /> {t("Research Graph")}</Link> : null}{detail.links.agent ? <Link to={detail.links.agent}>{t("Agent run")} <ArrowRight size={12} /></Link> : null}{(detail.links.evidence ?? []).map((href, index) => <Link key={href} to={href}>{t("Evidence")} {index + 1}</Link>)}</div>
    <p>{t("Attribution")}: {detail.attribution.available ? "persisted evidence linked" : "unavailable — no attribution is derived in the browser or projection"}.</p>
    {detail.unresolved.length ? <ul className="linked-strategy-unresolved">{detail.unresolved.map((item, index) => <li key={`${String(item.relation ?? "relation")}-${index}`}><code>{String(item.relation ?? "relationship")}</code><span>{String(item.reason ?? "unavailable")}</span></li>)}</ul> : null}
    <small><LockKeyhole size={12} /> Canonical IDs only. Hidden chain-of-thought is not persisted or projected. Browser financial/statistical recomputation = false.</small>
  </section>;
}
