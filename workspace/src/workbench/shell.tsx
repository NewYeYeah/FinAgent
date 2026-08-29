import {
  Activity,
  Boxes,
  ChartCandlestick,
  CircleGauge,
  Command,
  FileSearch,
  FlaskConical,
  Gauge,
  GitBranch,
  LayoutDashboard,
  LockKeyhole,
  Network,
  Radio,
  Settings2,
  ShieldCheck,
  SlidersHorizontal,
  Workflow,
} from "lucide-react";
import { NavLink } from "react-router-dom";
import type { ReactNode } from "react";

import { ReadOnlyBanner } from "../components";
import {
  WORKBENCH_CONTEXT_KEYS,
  WorkbenchContextProvider,
  useWorkbenchContext,
  type WorkbenchContextKey,
} from "./context";
import {
  defaultPanelRegistry,
  type WorkbenchModule,
  type WorkbenchPanelDescriptor,
} from "./panels";
import { WorkbenchQueryProvider } from "./query";

const ICONS: Record<WorkbenchModule, ReactNode> = {
  "command-center": <LayoutDashboard size={17} />,
  agent: <Boxes size={17} />,
  strategy: <ChartCandlestick size={17} />,
  factors: <FlaskConical size={17} />,
  portfolio: <Activity size={17} />,
  execution: <Workflow size={17} />,
  risk: <Gauge size={17} />,
  operations: <CircleGauge size={17} />,
  evidence: <FileSearch size={17} />,
  governance: <Network size={17} />,
  configuration: <SlidersHorizontal size={17} />,
  live: <Radio size={17} />,
};

const CONTEXT_LABELS: Record<WorkbenchContextKey, string> = {
  project_id: "Project",
  thread_id: "Thread",
  run_id: "Run",
  program_id: "Program",
  factor_id: "Factor",
  portfolio_validation_id: "Portfolio",
  strategy_id: "Strategy",
  reserve_id: "Reserve",
  asset_id: "Asset",
  date_range: "Range",
  session_date: "Session",
  fold_id: "Fold",
  environment: "Environment",
};

function NavigationItem({ panel }: { panel: WorkbenchPanelDescriptor }) {
  const icon = ICONS[panel.module];
  if (panel.status === "reserved" || !panel.route) {
    return (
      <span className="workbench-nav-item workbench-nav-reserved" aria-disabled="true">
        {icon}
        <span>{panel.title}</span>
        <small>planned</small>
      </span>
    );
  }
  return (
    <NavLink className="workbench-nav-item" to={panel.route} end={panel.route === "/"}>
      {icon}
      <span>{panel.title}</span>
    </NavLink>
  );
}

export function ContextBar() {
  const { context, lastEvent, clear } = useWorkbenchContext();
  const active = WORKBENCH_CONTEXT_KEYS.flatMap((key) => {
    const value = context[key];
    return value ? [{ key, value }] : [];
  });
  return (
    <div className="workbench-context-bar" data-testid="workbench-context-bar">
      <div className="workbench-context-values">
        <strong>Context</strong>
        {active.length ? (
          active.map(({ key, value }) => (
            <span className="context-chip" key={key} title={value}>
              <b>{CONTEXT_LABELS[key]}</b>
              <span className="mono">{value}</span>
            </span>
          ))
        ) : (
          <span className="workbench-context-empty">No linked selection</span>
        )}
      </div>
      <div className="workbench-context-actions">
        {lastEvent ? <span className="context-event mono">{lastEvent}</span> : null}
        {active.length ? (
          <button className="context-clear" type="button" onClick={() => clear()}>
            Clear
          </button>
        ) : null}
        <button className="workbench-slot-button" type="button" disabled title="V3-2B configuration registry">
          <Settings2 size={14} /> Config
        </button>
        <button className="workbench-slot-button" type="button" disabled title="V3-2B/V3-2C command catalog and gateway">
          <Command size={14} /> Commands
        </button>
      </div>
    </div>
  );
}

export function WorkbenchShell({ children }: { children: ReactNode }) {
  const panels = defaultPanelRegistry.list();
  return (
    <div className="workbench-shell">
      <aside className="workbench-sidebar">
        <div className="brand workbench-brand">
          <div className="brand-mark">FA</div>
          <div>
            <strong>FinAgent</strong>
            <span>Workbench Foundation</span>
          </div>
        </div>
        <nav className="workbench-navigation" aria-label="FinAgent Workbench modules">
          {panels.map((panel) => (
            <NavigationItem key={panel.panel_id} panel={panel} />
          ))}
        </nav>
        <div className="workbench-sidebar-footer">
          <ShieldCheck size={15} />
          <div>
            <strong>Evidence Plane</strong>
            <span>GET-only · Control disabled</span>
          </div>
        </div>
      </aside>
      <main className="workbench-main">
        <ReadOnlyBanner />
        <ContextBar />
        <div className="workbench-main-slot" data-slot="chart-workspace">
          {children}
        </div>
      </main>
    </div>
  );
}

export function WorkbenchProviders({ children }: { children: ReactNode }) {
  return (
    <WorkbenchQueryProvider>
      <WorkbenchContextProvider>{children}</WorkbenchContextProvider>
    </WorkbenchQueryProvider>
  );
}

export function WorkbenchInspectorSlot({
  title = "Inspector",
  children,
}: {
  title?: string;
  children: ReactNode;
}) {
  return (
    <aside className="workbench-inspector-slot" data-slot="inspector">
      <header>
        <GitBranch size={15} />
        <strong>{title}</strong>
      </header>
      <div>{children}</div>
    </aside>
  );
}

export function WorkbenchReservedSlot({
  kind,
  title,
  detail,
}: {
  kind: "config" | "command" | "chart";
  title: string;
  detail: string;
}) {
  const icon = kind === "config" ? <SlidersHorizontal size={18} /> : kind === "command" ? <Command size={18} /> : <ChartCandlestick size={18} />;
  return (
    <section className="workbench-reserved-slot" data-slot={kind}>
      {icon}
      <div>
        <strong>{title}</strong>
        <p>{detail}</p>
      </div>
      <LockKeyhole size={14} />
    </section>
  );
}
