import { QueryClient, QueryClientProvider, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link2, LockKeyhole } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, Navigate, useParams } from "react-router-dom";

import { workspaceApi } from "../api";
import { ErrorState, LoadingState, StatusBadge } from "../components";
import { agentQueryKeys } from "./agentQueries";
import { useWorkbenchContext, workbenchContextSearch } from "./context";
import { ResearchContext, ResearchObjective, ResearchToolCard } from "./research";
import type { ResearchState, ResearchTool } from "./researchTypes";
import { R4_ACCEPTED_TERMINAL, R4TerminalSummary } from "./researchTerminal";
import { WorkbenchInspectorSlot } from "./shell";
import { useWorkbenchSse } from "./stream";
import type { AgentActiveRunProjectionV3 } from "./streamTypes";
import type {
  AgentArtifactRefV3,
  AgentProjectResponseV3,
  AgentProjectsResponseV3,
  AgentRunResponseV3,
  AgentRunSummaryV3,
  AgentThreadResponseV3,
} from "./types";

function shortIdentity(value: string, max = 34) {
  return value.length > max ? `${value.slice(0, max - 1)}…` : value;
}

function artifactReferencePath(artifact: AgentArtifactRefV3, search: string): string {
  const kind = artifact.artifact_type === "factor" ? "factor" : "evidence";
  return `/ref/${kind}/${encodeURIComponent(artifact.artifact_id)}${search}`;
}

function ProjectIndex({ projects, selectedProjectId, onSelect }: {
  projects: AgentProjectsResponseV3["items"];
  selectedProjectId?: string;
  onSelect: (projectId: string) => void;
}) {
  return <section className="agent-index-section"><h3>Projects</h3><div className="agent-select-list">
    {projects.map((project) => <button className={`agent-select-button ${project.project_id === selectedProjectId ? "selected" : ""}`} key={project.project_id} type="button" onClick={() => onSelect(project.project_id)}>
      <strong>{project.label}</strong><small>{project.thread_count} threads · {project.run_count} runs · {project.identity_source}</small>
    </button>)}
  </div></section>;
}

function ThreadIndex({ project, selectedThreadId, onSelect }: {
  project?: AgentProjectResponseV3;
  selectedThreadId?: string;
  onSelect: (threadId: string) => void;
}) {
  if (!project) return null;
  return <section className="agent-index-section"><h3>Threads</h3><div className="agent-select-list">
    {project.threads.map((thread) => <button className={`agent-select-button ${thread.thread_id === selectedThreadId ? "selected" : ""}`} key={thread.thread_id} type="button" onClick={() => onSelect(thread.thread_id)}>
      <strong>{thread.label}</strong><small>{thread.run_count} runs · {thread.identity_source}</small>
    </button>)}
  </div></section>;
}

function RunIndex({ thread, selectedRunId, onSelect }: {
  thread?: AgentThreadResponseV3;
  selectedRunId?: string;
  onSelect: (run: AgentRunSummaryV3) => void;
}) {
  if (!thread) return null;
  return <section className="agent-index-section"><h3>Runs</h3><div className="agent-select-list">
    {thread.runs.map((run) => <button className={`agent-select-button ${run.run_id === selectedRunId ? "selected" : ""}`} key={run.run_id} type="button" onClick={() => onSelect(run)}>
      <strong>{run.objective}</strong><small>{run.status} · {run.trigger_type} · {run.item_count} items</small>
    </button>)}
  </div></section>;
}

function ActivityPane({ runDetail }: { runDetail?: AgentRunResponseV3 }) {
  const { context } = useWorkbenchContext();
  const search = workbenchContextSearch(context);
  const verified = useMemo(() => new Map((runDetail?.artifact_refs ?? []).map((ref) => [ref.artifact_id, ref])), [runDetail]);
  if (!runDetail) {
    return <section className="agent-activity-pane"><header className="agent-pane-header"><strong>Persisted action / result / decision</strong><span className="agent-contract-pill">authoritative projection</span></header>
      <div className="agent-empty-copy">Select a Project, Thread and Run. This workspace renders persisted explicit research artifacts only; transport events never become a second authoritative state.</div></section>;
  }
  const run = runDetail.run;
  const visibleItems = run.items.filter((item, index, items) => {
    const tool = item.metadata.research_tool;
    return !tool || !items.slice(index + 1).some((later) => later.call_id === item.call_id);
  });
  return <section className="agent-activity-pane"><header className="agent-pane-header"><div><strong>{run.objective}</strong><div className="mono subtle">{run.run_id}</div></div><StatusBadge value={run.status} /></header>
    <ol className="agent-activity-list">{visibleItems.map((item) => <li key={item.item_id}>
      {item.metadata.research_tool ? <ResearchToolCard tool={item.metadata.research_tool as ResearchTool} status={item.status} /> : <>
        <div className="agent-activity-title"><strong>{item.title}</strong><StatusBadge value={item.status} tone="neutral" /><span className="mono subtle">{item.item_type}</span></div>
        <time>{item.occurred_at}</time>{item.summary ? <p>{item.summary}</p> : null}
        {item.evidence_ids.length ? <div className="agent-evidence-refs">{item.evidence_ids.map((evidenceId) => {
          const ref = verified.get(evidenceId);
          return ref ? <Link className="agent-evidence-ref" key={evidenceId} to={artifactReferencePath(ref, search)}><Link2 size={11} /> {shortIdentity(evidenceId, 30)}</Link>
            : <span className="agent-evidence-unresolved mono" key={evidenceId} title="Unresolved audit identifier; not promoted to Workspace evidence">unresolved:{shortIdentity(evidenceId, 25)}</span>;
        })}</div> : null}
      </>}
    </li>)}</ol>
  </section>;
}

function ArtifactLink({ artifact }: { artifact: AgentArtifactRefV3 }) {
  const { context } = useWorkbenchContext();
  return <Link className="agent-artifact-link" to={artifactReferencePath(artifact, workbenchContextSearch(context))}>
    <span className="mono">{shortIdentity(artifact.artifact_id, 28)}</span><span>{artifact.artifact_type} · {artifact.authority}</span>
  </Link>;
}

function Inspector({ runDetail, research }: { runDetail?: AgentRunResponseV3; research?: ResearchState }) {
  const { context } = useWorkbenchContext();
  if (!runDetail) return <WorkbenchInspectorSlot><div className="agent-empty-copy">Run identity, research state, governance and verified evidence links appear here.</div></WorkbenchInspectorSlot>;
  const { run, summary } = runDetail;
  return <WorkbenchInspectorSlot title="Research Inspector">
    {research?.resources ? <ResearchContext state={research} /> : null}
    <section className="agent-inspector-block"><h3>Identity & deep links</h3><dl className="agent-inspector-grid">
      <div><dt>Project</dt><dd className="mono">{summary.project_id}</dd></div><div><dt>Thread</dt><dd className="mono">{summary.thread_id}</dd></div>
      <div><dt>Run</dt><dd className="mono">{summary.run_id}</dd></div><div><dt>Actor</dt><dd>{run.actor}</dd></div>
      <div><dt>Trigger</dt><dd>{run.trigger_type}</dd></div><div><dt>Latency</dt><dd>{(run.latency_ms / 1000).toFixed(2)} s</dd></div>
      <div><dt>Project ID source</dt><dd>{summary.project_identity_source}</dd></div><div><dt>Thread ID source</dt><dd>{summary.thread_identity_source}</dd></div>
    </dl><div className="agent-identity-links">
      <Link to={`/ref/agent_run/${encodeURIComponent(summary.run_id)}${workbenchContextSearch(context)}`}>Typed Run evidence reference</Link>
      <a href="/widgets?surface=configs">Configuration identity catalog</a>
      {research?.market_state ? <a href="#current-market-state">MarketState model · {research.market_state.model_id}</a> : null}
      <a href={R4_ACCEPTED_TERMINAL.attestationUrl}>Accepted R4 campaign attestation</a>
    </div></section>
    <section className="agent-inspector-block"><h3>Verified artifacts</h3>{runDetail.artifact_refs.length ? <div className="agent-artifact-list">{runDetail.artifact_refs.map((artifact) => <ArtifactLink artifact={artifact} key={artifact.artifact_id} />)}</div> : <div className="agent-empty-copy">No Workspace-verified artifacts are linked to this run.</div>}
      {runDetail.unresolved_artifact_count ? <p className="agent-authority-note">{runDetail.unresolved_artifact_count} audit identifier(s) remain unresolved and are not treated as product evidence.</p> : null}</section>
    <section className="agent-inspector-block"><h3>Governance</h3><pre className="json-view">{JSON.stringify(run.governance, null, 2)}</pre></section>
    <section className="agent-inspector-block"><h3>Reasoning boundary</h3><p className="agent-authority-note"><LockKeyhole size={12} /> Hidden chain-of-thought is not persisted or projected. Only explicit hypothesis, action, result and decision records are rendered.</p></section>
  </WorkbenchInspectorSlot>;
}

function AgentWorkspaceContent() {
  const { context, select } = useWorkbenchContext();
  const queryClient = useQueryClient();
  const runId = context.run_id ?? "";

  const projectsQuery = useQuery({ queryKey: agentQueryKeys.projects(), queryFn: workspaceApi.agentProjectsV3, retry: false });
  const runQuery = useQuery({ queryKey: agentQueryKeys.run(runId), queryFn: () => workspaceApi.agentRunV3(runId), enabled: Boolean(runId), retry: false });
  const effectiveProjectId = context.project_id ?? runQuery.data?.summary.project_id;
  const effectiveThreadId = context.thread_id ?? runQuery.data?.summary.thread_id;
  const projectQuery = useQuery({ queryKey: agentQueryKeys.project(effectiveProjectId ?? ""), queryFn: () => workspaceApi.agentProjectV3(effectiveProjectId ?? ""), enabled: Boolean(effectiveProjectId), retry: false });
  const threadQuery = useQuery({ queryKey: agentQueryKeys.thread(effectiveThreadId ?? ""), queryFn: () => workspaceApi.agentThreadV3(effectiveThreadId ?? ""), enabled: Boolean(effectiveThreadId), retry: false });

  const streamEnabled = Boolean(runId && runQuery.data && !runQuery.data.summary.finished_at);
  const agentStream = useWorkbenchSse<AgentActiveRunProjectionV3>({
    path: runId ? `/api/v3/streams/agent/runs/${encodeURIComponent(runId)}` : "",
    eventType: "agent_run_snapshot",
    identity: runId,
    enabled: streamEnabled,
    onProjection: (projection) => {
      if (projection.run_id === runId) void queryClient.invalidateQueries({ queryKey: agentQueryKeys.run(runId), exact: true });
    },
  });

  useEffect(() => {
    if (!runId || runQuery.data) return;
    const timer = setInterval(() => {
      void runQuery.refetch();
      void queryClient.invalidateQueries({ queryKey: agentQueryKeys.projects(), exact: true });
    }, 1000);
    const deadline = setTimeout(() => clearInterval(timer), 30000);
    return () => { clearInterval(timer); clearTimeout(deadline); };
  }, [queryClient, runId, runQuery.data, runQuery.refetch]);

  useEffect(() => {
    if (!runQuery.data) return;
    const { project_id, thread_id, run_id } = runQuery.data.summary;
    if (context.project_id !== project_id || context.thread_id !== thread_id || context.run_id !== run_id) {
      select({ project_id, thread_id, run_id }, "run_selected", { replace: true });
    }
    void queryClient.invalidateQueries({ queryKey: agentQueryKeys.projects(), exact: true });
    void queryClient.invalidateQueries({ queryKey: agentQueryKeys.project(project_id), exact: true });
    void queryClient.invalidateQueries({ queryKey: agentQueryKeys.thread(thread_id), exact: true });
  }, [context.project_id, context.run_id, context.thread_id, queryClient, runQuery.data, select]);

  const objectiveControl = <ResearchObjective onStarted={(newRunId) => {
    void queryClient.invalidateQueries({ queryKey: agentQueryKeys.projects(), exact: true });
    select({ project_id: null, thread_id: null, run_id: newRunId }, "run_selected");
  }} />;

  if (projectsQuery.isPending) return <LoadingState label="Loading Agent project index" />;
  if (projectsQuery.error) return <ErrorState error={projectsQuery.error} />;

  const projectError = projectQuery.error;
  const threadError = threadQuery.error;
  const runError = runQuery.error;
  const streamLabel = runQuery.data?.summary.finished_at ? "SSE terminal" : `SSE ${agentStream.status}`;
  const agUiEvents = agentStream.lastProjection?.ag_ui_events?.length ?? 0;

  return <div className="agent-workbench-page">
    <header className="agent-workbench-header"><div><span className="eyebrow">Workbench-2 · Agent-first research</span><h1>Research Workspace</h1><p>Objective → persisted actions/results → explicit decision → evidence.</p></div>
      <div className="agent-header-contracts"><span className="agent-contract-pill">{streamLabel}</span><span className="agent-contract-pill">AG-UI {agUiEvents} events · server projection authoritative</span><span className="agent-contract-pill">development only · no hidden reasoning</span></div></header>
    <R4TerminalSummary />
    {objectiveControl}
    {!projectsQuery.data?.configured ? <div className="agent-empty-copy">No canonical Agent audit database is configured for the Evidence Plane. The accepted R4 terminal above remains reviewable; no run is fabricated.</div> : <>
      {projectError || threadError || runError ? <ErrorState error={projectError ?? threadError ?? runError} /> : null}
      <div className="agent-workbench-grid"><aside className="agent-index-pane"><header className="agent-pane-header"><strong>Project / Thread / Run</strong><span className="mono subtle">{projectsQuery.data.items.length} projects</span></header><div className="agent-pane-body">
        <ProjectIndex projects={projectsQuery.data.items} selectedProjectId={effectiveProjectId} onSelect={(projectId) => select({ project_id: projectId, thread_id: null, run_id: null }, "project_selected")} />
        {effectiveProjectId && projectQuery.isPending ? <LoadingState label="Loading threads" /> : null}
        <ThreadIndex project={projectQuery.data} selectedThreadId={effectiveThreadId} onSelect={(threadId) => select({ project_id: projectQuery.data?.project_id ?? effectiveProjectId, thread_id: threadId, run_id: null }, "thread_selected")} />
        {effectiveThreadId && threadQuery.isPending ? <LoadingState label="Loading runs" /> : null}
        <RunIndex thread={threadQuery.data} selectedRunId={runId} onSelect={(run) => select({ project_id: run.project_id, thread_id: run.thread_id, run_id: run.run_id }, "run_selected")} />
      </div></aside>
      {runId && runQuery.isPending ? <section className="agent-activity-pane"><LoadingState label="Loading run activity" /></section> : <ActivityPane runDetail={runQuery.data} />}
      <Inspector runDetail={runQuery.data} research={runQuery.data?.run.research} />
      </div>
    </>}
  </div>;
}

export function AgentWorkbenchPage() {
  const [client] = useState(() => new QueryClient({ defaultOptions: { queries: { refetchOnWindowFocus: false, staleTime: 1_500, retry: false }, mutations: { retry: false } } }));
  return <QueryClientProvider client={client}><AgentWorkspaceContent /></QueryClientProvider>;
}

export function LegacyAgentRunRedirect() {
  const { runId = "" } = useParams();
  return <Navigate replace to={`/agent?run=${encodeURIComponent(decodeURIComponent(runId))}`} />;
}
