import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import {
  CheckCircle2,
  CircleOff,
  Clock3,
  Command,
  History,
  LockKeyhole,
  Play,
  RefreshCw,
  ShieldAlert,
  X,
} from "lucide-react";
import { Link } from "react-router-dom";

import { controlApi, workspaceApi } from "../api";
import { StatusBadge } from "../components";
import {
  WORKBENCH_CONTEXT_KEYS,
  useWorkbenchContext,
  workbenchContextSearch,
} from "./context";
import type {
  CommandRecordV3,
  CommandRunStateV3,
  ControlCommandCatalogV3,
  ControlCommandSpecV3,
  ControlStatusV3,
} from "./controlTypes";
import type { ConfigRegistryResponseV3, ConfigSnapshotV3 } from "./types";
import "./control.css";

const TERMINAL = new Set<CommandRunStateV3>(["succeeded", "failed", "rejected"]);

interface ControlPlaneContextValue {
  status: ControlStatusV3 | null;
  catalog: ControlCommandCatalogV3 | null;
  available: boolean;
  loading: boolean;
  error: Error | null;
  refresh: () => Promise<void>;
}

const ControlPlaneContext = createContext<ControlPlaneContextValue | null>(null);

export function ControlPlaneProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<ControlStatusV3 | null>(null);
  const [catalog, setCatalog] = useState<ControlCommandCatalogV3 | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [nextStatus, nextCatalog] = await Promise.all([
        controlApi.status(),
        controlApi.commands(),
      ]);
      setStatus(nextStatus);
      setCatalog(nextCatalog);
      setError(null);
    } catch (reason) {
      setStatus(null);
      setCatalog(null);
      setError(reason instanceof Error ? reason : new Error(String(reason)));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 10_000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const value = useMemo<ControlPlaneContextValue>(
    () => ({
      status,
      catalog,
      available: Boolean(status?.control_plane_enabled && catalog?.control_plane_enabled),
      loading,
      error,
      refresh,
    }),
    [catalog, error, loading, refresh, status],
  );
  return <ControlPlaneContext.Provider value={value}>{children}</ControlPlaneContext.Provider>;
}

export function useControlPlane(): ControlPlaneContextValue {
  const value = useContext(ControlPlaneContext);
  if (!value) throw new Error("useControlPlane must be used within ControlPlaneProvider");
  return value;
}

function contextPayload(context: ReturnType<typeof useWorkbenchContext>["context"]): Record<string, string> {
  const output: Record<string, string> = {};
  for (const key of WORKBENCH_CONTEXT_KEYS) {
    const value = context[key];
    if (value) output[key] = value;
  }
  return output;
}

function requestId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return `workbench-${crypto.randomUUID()}`;
  }
  return `workbench-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function snapshotChoices(
  registry: ConfigRegistryResponseV3 | null,
  command: ControlCommandSpecV3 | undefined,
): ConfigSnapshotV3[] {
  if (!registry || !command?.config_descriptor_ids.length) return [];
  const allowed = new Set(command.config_descriptor_ids);
  return registry.snapshots.filter((item) => allowed.has(item.descriptor_id));
}

function CommandRunInspector({ record }: { record: CommandRecordV3 }) {
  const { context } = useWorkbenchContext();
  const search = workbenchContextSearch(context);
  return (
    <section className="control-run-inspector" aria-label="Command Run Inspector">
      <header>
        <div>
          <span className="eyebrow">CommandRun</span>
          <Link
            className="mono"
            to={`/ref/command_run/${encodeURIComponent(record.run.command_run_id)}${search}`}
          >
            {record.run.command_run_id}
          </Link>
        </div>
        <StatusBadge value={record.run.state} />
      </header>
      <dl>
        <dt>Command</dt>
        <dd className="mono">{record.run.command_id}</dd>
        <dt>Intent</dt>
        <dd className="mono">{record.intent.intent_id}</dd>
        <dt>Actor</dt>
        <dd>{record.intent.requested_by}</dd>
        <dt>Config</dt>
        <dd className="mono">
          {record.intent.config_snapshot_id ? (
            <Link
              to={`/ref/config_snapshot/${encodeURIComponent(record.intent.config_snapshot_id)}${search}`}
            >
              {record.intent.config_snapshot_id}
            </Link>
          ) : "none"}
        </dd>
      </dl>
      <div className="control-event-list">
        {record.events.map((event) => (
          <div key={event.event_id} className="control-event-row">
            <span className="mono">#{event.sequence}</span>
            <div>
              <strong>{event.event_type}</strong>
              <small>{new Date(event.occurred_at).toLocaleString()}</small>
              {event.message ? <p>{event.message}</p> : null}
            </div>
            <StatusBadge value={event.state} tone="neutral" />
          </div>
        ))}
      </div>
      {record.result ? (
        <div className="control-result-box">
          <strong>{record.result.status}</strong>
          <p>{record.result.message || "No result message."}</p>
          {record.result.evidence_ids.length ? (
            <div>
              <span>Evidence</span>
              {record.result.evidence_ids.map((item) => (
                <Link
                  className="mono"
                  key={item}
                  to={`/ref/evidence/${encodeURIComponent(item)}${search}`}
                >
                  {item}
                </Link>
              ))}
            </div>
          ) : null}
          {record.artifact_paths.length ? (
            <div>
              <span>Artifacts</span>
              {record.artifact_paths.map((item) => (
                <code key={item}>{item}</code>
              ))}
            </div>
          ) : null}
        </div>
      ) : (
        <div className="control-running-box">
          <Clock3 size={14} /> Persisted run is active; status is polled from the Control Plane.
        </div>
      )}
    </section>
  );
}

export function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const control = useControlPlane();
  const { context } = useWorkbenchContext();
  const [registry, setRegistry] = useState<ConfigRegistryResponseV3 | null>(null);
  const [registryError, setRegistryError] = useState<Error | null>(null);
  const [selectedId, setSelectedId] = useState("");
  const [snapshotId, setSnapshotId] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<Error | null>(null);
  const [activeRun, setActiveRun] = useState<CommandRecordV3 | null>(null);
  const [recentRuns, setRecentRuns] = useState<CommandRecordV3[]>([]);

  const commands = control.catalog?.items ?? [];
  const selected = commands.find((item) => item.command_id === selectedId) ?? commands[0];
  const snapshots = snapshotChoices(registry, selected);
  const selectedSnapshot = snapshots.find((item) => item.snapshot_id === snapshotId) ?? snapshots[0];
  const needsPortfolioContext = selected?.command_id === "review.export_bundle";
  const portfolioContextReady = Boolean(context.portfolio_validation_id);
  const configReady = !selected?.config_descriptor_ids.length || Boolean(selectedSnapshot);
  const confirmationReady = !selected?.requires_confirmation || confirmed;
  const executable = Boolean(
    control.available &&
      selected?.control_execution_enabled &&
      configReady &&
      confirmationReady &&
      (!needsPortfolioContext || portfolioContextReady),
  );

  useEffect(() => {
    if (!open) return;
    setSelectedId((current) => current || commands[0]?.command_id || "");
    void workspaceApi
      .configRegistryV3()
      .then((data) => {
        setRegistry(data);
        setRegistryError(null);
      })
      .catch((reason) => setRegistryError(reason instanceof Error ? reason : new Error(String(reason))));
    void controlApi
      .runs(20)
      .then((data) => setRecentRuns(data.items))
      .catch(() => setRecentRuns([]));
  }, [commands, open]);

  useEffect(() => {
    setSnapshotId("");
    setConfirmed(false);
    setSubmitError(null);
  }, [selected?.command_id]);

  useEffect(() => {
    if (!activeRun || TERMINAL.has(activeRun.run.state)) return;
    const timer = window.setInterval(() => {
      void controlApi
        .run(activeRun.run.command_run_id)
        .then((next) => {
          setActiveRun(next);
          if (TERMINAL.has(next.run.state)) {
            void controlApi.runs(20).then((data) => setRecentRuns(data.items));
          }
        })
        .catch((reason) => setSubmitError(reason instanceof Error ? reason : new Error(String(reason))));
    }, 600);
    return () => window.clearInterval(timer);
  }, [activeRun]);

  if (!open) return null;

  async function execute() {
    if (!selected || !executable) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      const response = await controlApi.createRun({
        request_id: requestId(),
        command_id: selected.command_id,
        config_snapshot_id: selectedSnapshot?.snapshot_id,
        context: contextPayload(context),
        confirmed,
        validation_id:
          selected.command_id === "review.export_bundle"
            ? context.portfolio_validation_id
            : undefined,
      });
      setActiveRun(response.data);
      if (response.status === 422) {
        setSubmitError(new Error(response.data.result?.message ?? "Command rejected"));
      }
      const latest = await controlApi.runs(20);
      setRecentRuns(latest.items);
    } catch (reason) {
      setSubmitError(reason instanceof Error ? reason : new Error(String(reason)));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="control-palette-backdrop" role="presentation" onMouseDown={onClose}>
      <aside
        className="control-palette"
        role="dialog"
        aria-modal="true"
        aria-label="FinAgent Command Palette"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="control-palette-header">
          <div>
            <span className="eyebrow">V3-2 · governed local Control Plane</span>
            <h2>Command Palette</h2>
          </div>
          <button type="button" onClick={onClose} aria-label="Close Command Palette">
            <X size={17} />
          </button>
        </header>

        <div className="control-boundary-note">
          {control.available ? <CheckCircle2 size={17} /> : <CircleOff size={17} />}
          <div>
            <strong>{control.available ? "Local Control Plane connected" : "Control Plane unavailable"}</strong>
            <p>
              {control.available
                ? `${control.status?.requested_by} · application_service_ready only · no L2/L3 authority`
                : "Start scripts/run_workbench_control.py on 127.0.0.1:8766. No fallback execution path is used."}
            </p>
          </div>
          <button type="button" onClick={() => void control.refresh()} title="Refresh control status">
            <RefreshCw size={15} />
          </button>
        </div>

        <div className="control-palette-body">
          <section className="control-command-list">
            <header>
              <Command size={15} />
              <strong>Allowlisted commands</strong>
            </header>
            {commands.map((command) => (
              <button
                type="button"
                key={command.command_id}
                className={command.command_id === selected?.command_id ? "selected" : ""}
                onClick={() => setSelectedId(command.command_id)}
              >
                <div>
                  <strong>{command.title}</strong>
                  <span className="mono">{command.command_id}</span>
                </div>
                <StatusBadge
                  value={command.control_execution_enabled ? "ready" : command.gateway_readiness}
                  tone={command.control_execution_enabled ? "good" : "neutral"}
                />
              </button>
            ))}
          </section>

          <section className="control-command-detail">
            {selected ? (
              <>
                <header>
                  <div>
                    <StatusBadge value={selected.level} tone="neutral" />
                    <StatusBadge value={selected.gateway_readiness} tone="neutral" />
                  </div>
                  <h3>{selected.title}</h3>
                  <p>{selected.description}</p>
                </header>
                <dl>
                  <dt>Binding</dt>
                  <dd className="mono">{selected.binding_ref}</dd>
                  <dt>Produces</dt>
                  <dd>{selected.produces.join(", ") || "none"}</dd>
                </dl>

                {selected.config_descriptor_ids.length ? (
                  <label className="control-field">
                    ConfigSnapshot
                    <select
                      value={selectedSnapshot?.snapshot_id ?? ""}
                      onChange={(event) => setSnapshotId(event.target.value)}
                      disabled={!selected.control_execution_enabled}
                    >
                      {!snapshots.length ? <option value="">No compatible snapshot</option> : null}
                      {snapshots.map((snapshot) => (
                        <option key={snapshot.snapshot_id} value={snapshot.snapshot_id}>
                          {snapshot.descriptor_id} · {snapshot.source_uri}
                        </option>
                      ))}
                    </select>
                  </label>
                ) : null}

                {needsPortfolioContext ? (
                  <div className={`control-context-requirement ${portfolioContextReady ? "ready" : "missing"}`}>
                    <strong>PortfolioValidation context</strong>
                    <span className="mono">{context.portfolio_validation_id ?? "not selected"}</span>
                  </div>
                ) : null}

                {selected.requires_confirmation ? (
                  <label className="control-confirmation">
                    <input
                      type="checkbox"
                      checked={confirmed}
                      onChange={(event) => setConfirmed(event.target.checked)}
                    />
                    I confirm this governed {selected.level} command and its bound ConfigSnapshot.
                  </label>
                ) : null}

                {!selected.control_execution_enabled ? (
                  <div className="control-disabled-reason">
                    <LockKeyhole size={15} />
                    This catalog entry is not executable because its reviewed application-service adapter is not ready.
                  </div>
                ) : null}
                {registryError ? <div className="control-error">{registryError.message}</div> : null}
                {submitError ? <div className="control-error">{submitError.message}</div> : null}

                <button
                  className="control-execute-button"
                  type="button"
                  disabled={!executable || submitting}
                  onClick={() => void execute()}
                >
                  <Play size={15} /> {submitting ? "Persisting command…" : "Create governed CommandRun"}
                </button>
              </>
            ) : (
              <p>No command metadata available.</p>
            )}
          </section>
        </div>

        <section className="control-run-area">
          <div className="control-active-run">
            {activeRun ? (
              <CommandRunInspector record={activeRun} />
            ) : (
              <div className="control-run-empty">
                <History size={18} /> Select or create a persisted CommandRun to inspect its lifecycle.
              </div>
            )}
          </div>
          <aside className="control-recent-runs">
            <header>
              <History size={14} />
              <strong>Recent runs</strong>
            </header>
            {recentRuns.map((record) => (
              <button
                type="button"
                key={record.run.command_run_id}
                onClick={() => setActiveRun(record)}
              >
                <span className="mono">{record.run.command_id}</span>
                <StatusBadge value={record.run.state} tone="neutral" />
                <small>{new Date(record.updated_at).toLocaleString()}</small>
              </button>
            ))}
            {!recentRuns.length ? <p>No persisted commands yet.</p> : null}
          </aside>
        </section>

        <footer className="control-palette-footer">
          <ShieldAlert size={14} />
          <span>
            Forbidden: production reserve · strategy promotion · PAPER mutation · broker order · live capital · arbitrary shell/Python.
          </span>
        </footer>
      </aside>
    </div>
  );
}
