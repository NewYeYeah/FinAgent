import { useEffect, useMemo } from "react";
import { Link2, LockKeyhole } from "lucide-react";
import { Link, Navigate, useParams } from "react-router-dom";

import { workspaceApi } from "../api";
import { ErrorState, LoadingState, StatusBadge } from "../components";
import { useWorkbenchContext } from "./context";
import { workbenchQueryKeys, useWorkbenchQuery } from "./query";
import { WorkbenchInspectorSlot } from "./shell";
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

function ProjectIndex({
  projects,
  selectedProjectId,
  onSelect,
}: {
  projects: AgentProjectsResponseV3["items"];
  selectedProjectId?: string;
  onSelect: (projectId: string) => void;
}) {
  return (
    <section className="agent-index-section">
      <h3>Projects</h3>
      <div className="agent-select-list">
        {projects.map((project) => (
          <button
            className={`agent-select-button ${project.project_id === selectedProjectId ? "selected" : ""}`}
            key={project.project_id}
            type="button"
            onClick={() => onSelect(project.project_id)}
          >
            <strong>{project.label}</strong>
            <small>
              {project.thread_count} threads · {project.run_count} runs · {project.identity_source}
            </small>
          </button>
        ))}
      </div>
    </section>
  );
}

function ThreadIndex({
  project,
  selectedThreadId,
  onSelect,
}: {
  project?: AgentProjectResponseV3;
  selectedThreadId?: string;
  onSelect: (threadId: string) => void;
}) {
  if (!project) return null;
  return (
    <section className="agent-index-section">
      <h3>Threads</h3>
      <div className="agent-select-list">
        {project.threads.map((thread) => (
          <button
            className={`agent-select-button ${thread.thread_id === selectedThreadId ? "selected" : ""}`}
            key={thread.thread_id}
            type="button"
            onClick={() => onSelect(thread.thread_id)}
          >
            <strong>{thread.label}</strong>
            <small>{thread.run_count} runs · {thread.identity_source}</small>
          </button>
        ))}
      </div>
    </section>
  );
}

function RunIndex({
  thread,
  selectedRunId,
  onSelect,
}: {
  thread?: AgentThreadResponseV3;
  selectedRunId?: string;
  onSelect: (run: AgentRunSummaryV3) => void;
}) {
  if (!thread) return null;
  return (
    <section className="agent-index-section">
      <h3>Runs</h3>
      <div className="agent-select-list">
        {thread.runs.map((run) => (
          <button
            className={`agent-select-button ${run.run_id === selectedRunId ? "selected" : ""}`}
            key={run.run_id}
            type="button"
            onClick={() => onSelect(run)}
          >
            <strong>{run.objective}</strong>
            <small>{run.status} · {run.trigger_type} · {run.item_count} items</small>
          </button>
        ))}
      </div>
    </section>
  );
}

function ActivityPane({ runDetail }: { runDetail?: AgentRunResponseV3 }) {
  const verified = useMemo(
    () => new Map((runDetail?.artifact_refs ?? []).map((ref) => [ref.artifact_id, ref])),
    [runDetail],
  );
  if (!runDetail) {
    return (
      <section className="agent-activity-pane">
        <header className="agent-pane-header">
          <strong>Activity</strong>
          <span className="agent-contract-pill">persisted review</span>
        </header>
        <div className="agent-empty-copy">
          Select a Project, Thread and Run. The activity surface projects canonical audit events only; hidden reasoning and Phoenix spans are not product state.
        </div>
      </section>
    );
  }
  const run = runDetail.run;
  return (
    <section className="agent-activity-pane">
      <header className="agent-pane-header">
        <div>
          <strong>{run.objective}</strong>
          <div className="mono subtle">{run.run_id}</div>
        </div>
        <StatusBadge value={run.status} />
      </header>
      <ol className="agent-activity-list">
        {run.items.map((item) => (
          <li key={item.item_id}>
            <div className="agent-activity-title">
              <strong>{item.title}</strong>
              <StatusBadge value={item.status} tone="neutral" />
              <span className="mono subtle">{item.item_type}</span>
            </div>
            <time>{item.occurred_at}</time>
            {item.summary ? <p>{item.summary}</p> : null}
            {item.evidence_ids.length ? (
              <div className="agent-evidence-refs">
                {item.evidence_ids.map((evidenceId) => {
                  const ref = verified.get(evidenceId);
                  return ref ? (
                    <Link className="agent-evidence-ref" key={evidenceId} to={ref.detail_url}>
                      <Link2 size={11} /> {shortIdentity(evidenceId, 30)}
                    </Link>
                  ) : (
                    <span className="agent-evidence-unresolved mono" key={evidenceId} title="Unresolved audit identifier; not promoted to Workspace evidence">
                      unresolved:{shortIdentity(evidenceId, 25)}
                    </span>
                  );
                })}
              </div>
            ) : null}
          </li>
        ))}
      </ol>
    </section>
  );
}

function ArtifactLink({ artifact }: { artifact: AgentArtifactRefV3 }) {
  return (
    <Link className="agent-artifact-link" to={artifact.detail_url}>
      <span className="mono">{shortIdentity(artifact.artifact_id, 28)}</span>
      <span>{artifact.artifact_type} · {artifact.authority}</span>
    </Link>
  );
}

function Inspector({ runDetail }: { runDetail?: AgentRunResponseV3 }) {
  if (!runDetail) {
    return (
      <WorkbenchInspectorSlot>
        <div className="agent-empty-copy">Run identity, governance and verified artifact references appear here.</div>
      </WorkbenchInspectorSlot>
    );
  }
  const { run, summary } = runDetail;
  return (
    <WorkbenchInspectorSlot title="Run Inspector">
      <section className="agent-inspector-block">
        <h3>Identity</h3>
        <dl className="agent-inspector-grid">
          <div><dt>Project</dt><dd className="mono">{summary.project_id}</dd></div>
          <div><dt>Thread</dt><dd className="mono">{summary.thread_id}</dd></div>
          <div><dt>Run</dt><dd className="mono">{summary.run_id}</dd></div>
          <div><dt>Actor</dt><dd>{run.actor}</dd></div>
          <div><dt>Trigger</dt><dd>{run.trigger_type}</dd></div>
          <div><dt>Latency</dt><dd>{(run.latency_ms / 1000).toFixed(2)} s</dd></div>
          <div><dt>Project ID source</dt><dd>{summary.project_identity_source}</dd></div>
          <div><dt>Thread ID source</dt><dd>{summary.thread_identity_source}</dd></div>
        </dl>
      </section>
      <section className="agent-inspector-block">
        <h3>Verified artifacts</h3>
        {runDetail.artifact_refs.length ? (
          <div className="agent-artifact-list">
            {runDetail.artifact_refs.map((artifact) => (
              <ArtifactLink artifact={artifact} key={artifact.artifact_id} />
            ))}
          </div>
        ) : (
          <div className="agent-empty-copy">No Workspace-verified artifacts are linked to this run.</div>
        )}
        {runDetail.unresolved_artifact_count ? (
          <p className="agent-authority-note">
            {runDetail.unresolved_artifact_count} audit identifier(s) remain unresolved and are not treated as product evidence.
          </p>
        ) : null}
      </section>
      <section className="agent-inspector-block">
        <h3>Governance</h3>
        <pre className="json-view">{JSON.stringify(run.governance, null, 2)}</pre>
      </section>
      <section className="agent-inspector-block">
        <h3>Reasoning boundary</h3>
        <p className="agent-authority-note">
          <LockKeyhole size={12} /> {runDetail.hidden_reasoning}. The Workbench renders governed actions and evidence, not hidden chain-of-thought.
        </p>
      </section>
    </WorkbenchInspectorSlot>
  );
}

export function AgentWorkbenchPage() {
  const { context, select } = useWorkbenchContext();

  const projectsQuery = useWorkbenchQuery({
    key: workbenchQueryKeys.agentProjects(),
    queryFn: workspaceApi.agentProjectsV3,
  });
  const runQuery = useWorkbenchQuery({
    key: workbenchQueryKeys.agentRun(context.run_id ?? ""),
    queryFn: () => workspaceApi.agentRunV3(context.run_id ?? ""),
    enabled: Boolean(context.run_id),
  });

  const effectiveProjectId = context.project_id ?? runQuery.data?.summary.project_id;
  const effectiveThreadId = context.thread_id ?? runQuery.data?.summary.thread_id;

  const projectQuery = useWorkbenchQuery({
    key: workbenchQueryKeys.agentProject(effectiveProjectId ?? ""),
    queryFn: () => workspaceApi.agentProjectV3(effectiveProjectId ?? ""),
    enabled: Boolean(effectiveProjectId),
  });
  const threadQuery = useWorkbenchQuery({
    key: workbenchQueryKeys.agentThread(effectiveThreadId ?? ""),
    queryFn: () => workspaceApi.agentThreadV3(effectiveThreadId ?? ""),
    enabled: Boolean(effectiveThreadId),
  });

  useEffect(() => {
    if (!runQuery.data) return;
    const { project_id, thread_id, run_id } = runQuery.data.summary;
    if (
      context.project_id === project_id &&
      context.thread_id === thread_id &&
      context.run_id === run_id
    ) return;
    select(
      { project_id, thread_id, run_id },
      "run_selected",
      { replace: true },
    );
  }, [context.project_id, context.run_id, context.thread_id, runQuery.data, select]);

  if (projectsQuery.isPending) return <LoadingState label="Loading Agent project index" />;
  if (projectsQuery.error) return <ErrorState error={projectsQuery.error} />;
  if (!projectsQuery.data?.configured) {
    return (
      <div className="agent-workbench-page">
        <div className="agent-workbench-header">
          <div>
            <span className="eyebrow">Agent · V3-1 projection</span>
            <h1>Agent Workbench</h1>
            <p>No canonical Agent audit database is configured for the Evidence Plane.</p>
          </div>
        </div>
      </div>
    );
  }

  const projectError = projectQuery.error;
  const threadError = threadQuery.error;
  const runError = runQuery.error;

  return (
    <div className="agent-workbench-page">
      <header className="agent-workbench-header">
        <div>
          <span className="eyebrow">Agent · V3-2A Workbench</span>
          <h1>Project → Thread → Run</h1>
          <p>Canonical V3-1 audit navigation with deterministic linked context and verified evidence references.</p>
        </div>
        <span className="agent-contract-pill">read-only · no hidden reasoning</span>
      </header>
      {projectError || threadError || runError ? (
        <ErrorState error={projectError ?? threadError ?? runError} />
      ) : null}
      <div className="agent-workbench-grid">
        <aside className="agent-index-pane">
          <header className="agent-pane-header">
            <strong>Index</strong>
            <span className="mono subtle">{projectsQuery.data.items.length} projects</span>
          </header>
          <div className="agent-pane-body">
            <ProjectIndex
              projects={projectsQuery.data.items}
              selectedProjectId={effectiveProjectId}
              onSelect={(projectId) =>
                select(
                  { project_id: projectId, thread_id: null, run_id: null },
                  "project_selected",
                )
              }
            />
            {projectQuery.isPending ? <LoadingState label="Loading threads" /> : null}
            <ThreadIndex
              project={projectQuery.data}
              selectedThreadId={effectiveThreadId}
              onSelect={(threadId) =>
                select(
                  {
                    project_id: projectQuery.data?.project_id ?? effectiveProjectId,
                    thread_id: threadId,
                    run_id: null,
                  },
                  "thread_selected",
                )
              }
            />
            {threadQuery.isPending ? <LoadingState label="Loading runs" /> : null}
            <RunIndex
              thread={threadQuery.data}
              selectedRunId={context.run_id}
              onSelect={(run) =>
                select(
                  {
                    project_id: run.project_id,
                    thread_id: run.thread_id,
                    run_id: run.run_id,
                  },
                  "run_selected",
                )
              }
            />
          </div>
        </aside>
        {runQuery.isPending ? (
          <section className="agent-activity-pane"><LoadingState label="Loading run activity" /></section>
        ) : (
          <ActivityPane runDetail={runQuery.data} />
        )}
        <Inspector runDetail={runQuery.data} />
      </div>
    </div>
  );
}

export function LegacyAgentRunRedirect() {
  const { runId = "" } = useParams();
  const decoded = decodeURIComponent(runId);
  return <Navigate replace to={`/agent?run=${encodeURIComponent(decoded)}`} />;
}
