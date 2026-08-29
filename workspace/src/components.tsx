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
          <NavLink to="/" end><LayoutDashboard size={17} /> Project</NavLink>
          <NavLink to="/research"><Search size={17} /> Research</NavLink>
          <NavLink to="/portfolio"><Activity size={17} /> Portfolio</NavLink>
          <NavLink to="/agent"><Boxes size={17} /> Agent</NavLink>
          <NavLink to="/widgets"><Network size={17} /> Widgets</NavLink>
        </nav>
        <div className="sidebar-footer"><ShieldCheck size={15} /> Read-only evidence</div>
      </aside>
      <main>
        <ReadOnlyBanner />
        {children}
      </main>
    </div>
  );
}

export function DataTable<T extends object>({
  data,
  columns,
  empty = "No rows",
}: {
  data: T[];
  columns: ColumnDef<T, unknown>[];
  empty?: string;
}) {
  const stableColumns = useMemo(() => columns, [columns]);
  const table = useReactTable({
    data,
    columns: stableColumns,
    getCoreRowModel: getCoreRowModel(),
  });
  if (!data.length) return <div className="empty-table">{empty}</div>;
  return (
    <div className="table-wrap">
      <table>
        <thead>
          {table.getHeaderGroups().map((headerGroup) => (
            <tr key={headerGroup.id}>
              {headerGroup.headers.map((header) => (
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
            <tr key={row.id}>
              {row.getVisibleCells().map((cell) => (
                <td key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Breadcrumbs({ items }: { items: { label: string; to?: string }[] }) {
  return (
    <div className="breadcrumbs">
      <GitBranch size={14} />
      {items.map((item, index) => (
        <span key={`${item.label}-${index}`}>
          {index > 0 ? <span className="breadcrumb-separator">/</span> : null}
          {item.to ? <NavLink to={item.to}>{item.label}</NavLink> : item.label}
        </span>
      ))}
    </div>
  );
}
