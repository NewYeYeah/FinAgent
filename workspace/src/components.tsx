import { useMemo } from "react";
import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
} from "@tanstack/react-table";
import { Activity, Boxes, GitBranch, LayoutDashboard, LockKeyhole, Search, ShieldCheck, Network } from "lucide-react";
import { NavLink } from "react-router-dom";

export function StatusBadge({ value, tone }: { value: string; tone?: string }) {
  const normalized = value.toLowerCase();
  const inferred =
    tone ??
    (normalized.includes("pass") || normalized.includes("frozen") || normalized.includes("untouched")
      ? "good"
      : normalized.includes("fail") || normalized.includes("error")
        ? "bad"
        : "neutral");
  return <span className={`badge badge-${inferred}`}>{value || "unknown"}</span>;
}

export function AuthorityBadge({ value }: { value: string }) {
  return <span className={`authority authority-${value}`}>{value}</span>;
}

export function MetricCard({
  label,
  value,
  detail,
  derived = false,
}: {
  label: string;
  value: string;
  detail?: string;
  derived?: boolean;
}) {
  return (
    <article className="metric-card">
      <div className="metric-label">
        {label}
        {derived ? <span className="derived-pill">derived</span> : null}
      </div>
      <strong>{value}</strong>
      {detail ? <small>{detail}</small> : null}
    </article>
  );
}

export function Panel({
  title,
  subtitle,
  actions,
  children,
}: {
  title: string;
  subtitle?: string;
  actions?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="panel">
      <header className="panel-header">
        <div>
          <h2>{title}</h2>
          {subtitle ? <p>{subtitle}</p> : null}
        </div>
        {actions ? <div>{actions}</div> : null}
      </header>
      <div className="panel-body">{children}</div>
    </section>
  );
}

export function ReadOnlyBanner() {
  return (
    <div className="readonly-banner">
      <LockKeyhole size={16} />
      <span>
        Evidence Plane is GET-only. The optional local Control Plane is separate and
        limited to reviewed L0/L1 application services; no Gate, reserve, promotion,
        PAPER, broker-order or live-capital authority.
      </span>
    </div>
  );
}

export function EmptyState({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="empty-state">
      <Boxes size={34} />
      <h3>{title}</h3>
      <p>{detail}</p>
    </div>
  );
}

export function LoadingState({ label = "Loading evidence" }: { label?: string }) {
  return (
    <div className="loading-state">
      <div className="spinner" />
      <span>{label}</span>
    </div>
  );
}

export function ErrorState({ error }: { error: unknown }) {
  return (
    <div className="error-state">
      <strong>Evidence could not be loaded</strong>
      <p>{error instanceof Error ? error.message : String(error)}</p>
    </div>
  );
}

export function WorkspaceShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="workspace-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">FA</div>
          <div>
            <strong>FinAgent</strong>
            <span>Evidence Workspace</span>
          </div>
        </div>
        <nav>
          <NavLink to="/" end>
            <LayoutDashboard size={17} /> Cockpit
          </NavLink>
          <NavLink to="/research">
            <ShieldCheck size={17} /> Research
          </NavLink>
          <NavLink to="/portfolio">
            <Activity size={17} /> Portfolio
          </NavLink>
          <NavLink to="/governance">
            <Network size={17} /> Governance
          </NavLink>
          <NavLink to="/reserve">
            <LockKeyhole size={17} /> Reserve
          </NavLink>
          <NavLink to="/agent">
            <Boxes size={17} /> Agent Runs
          </NavLink>
          <NavLink to="/widgets">
            <Search size={17} /> Widget Catalog
          </NavLink>
        </nav>
        <div className="sidebar-footer">
          <GitBranch size={15} />
          <span>A5-4 · reserve evidence</span>
        </div>
      </aside>
      <main>
        <ReadOnlyBanner />
        {children}
      </main>
    </div>
  );
}

export function EvidenceTable<T extends object>({
  data,
  columns,
  onRowClick,
}: {
  data: T[];
  columns: ColumnDef<T, unknown>[];
  onRowClick?: (row: T) => void;
}) {
  const stableColumns = useMemo(() => columns, [columns]);
  const table = useReactTable({
    data,
    columns: stableColumns,
    getCoreRowModel: getCoreRowModel(),
  });
  return (
    <div className="table-wrap">
      <table>
        <thead>
          {table.getHeaderGroups().map((group) => (
            <tr key={group.id}>
              {group.headers.map((header) => (
                <th key={header.id}>
                  {header.isPlaceholder
                    ? null
                    : flexRender(header.column.columnDef.header, header.getContext())}
                </th>
              ))}
            </tr>
          ))}
        </thead>
        <tbody>
          {table.getRowModel().rows.map((row) => (
            <tr
              key={row.id}
              className={onRowClick ? "clickable" : ""}
              onClick={() => onRowClick?.(row.original)}
            >
              {row.getVisibleCells().map((cell) => (
                <td key={cell.id}>
                  {flexRender(cell.column.columnDef.cell, cell.getContext())}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function PageHeader({
  eyebrow,
  title,
  description,
  children,
}: {
  eyebrow: string;
  title: string;
  description: string;
  children?: React.ReactNode;
}) {
  return (
    <header className="page-header">
      <div>
        <span className="eyebrow">{eyebrow}</span>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {children ? <div className="page-actions">{children}</div> : null}
    </header>
  );
}
