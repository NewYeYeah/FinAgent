import { useMemo } from "react";
import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
} from "@tanstack/react-table";
import { Activity, Boxes, GitBranch, LayoutDashboard, LockKeyhole, Search, ShieldCheck, Network } from "lucide-react";
import { NavLink } from "react-router-dom";

import { useWorkbenchI18n } from "./i18n";

export function StatusBadge({ value, tone }: { value: string; tone?: string }) {
  const { t } = useWorkbenchI18n();
  const normalized = value.toLowerCase();
  const requested = tone === "positive" ? "good" : tone === "negative" ? "bad" : tone;
  const inferred =
    requested ??
    (normalized.includes("pass") || normalized.includes("frozen") || normalized.includes("untouched")
      ? "good"
      : normalized.includes("fail") || normalized.includes("error")
        ? "bad"
        : normalized.includes("warn")
          ? "warning"
          : "neutral");
  return <span className={`badge badge-${inferred}`}>{value || t("unknown")}</span>;
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
  const { t } = useWorkbenchI18n();
  return (
    <article className="metric-card">
      <div className="metric-label">
        {t(label)}
        {derived ? <span className="derived-pill">{t("derived")}</span> : null}
      </div>
      <strong>{value}</strong>
      {detail ? <small>{t(detail)}</small> : null}
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
  const { t } = useWorkbenchI18n();
  return (
    <section className="panel">
      <header className="panel-header">
        <div>
          <h2>{t(title)}</h2>
          {subtitle ? <p>{t(subtitle)}</p> : null}
        </div>
        {actions ? <div>{actions}</div> : null}
      </header>
      <div className="panel-body">{children}</div>
    </section>
  );
}

export function ReadOnlyBanner() {
  const { t } = useWorkbenchI18n();
  return (
    <div className="readonly-banner">
      <LockKeyhole size={16} />
      <span>{t("Evidence Plane is GET-only. The optional local Control Plane is separate and limited to reviewed L0/L1 application services; no Gate, reserve, promotion, PAPER, broker-order or live-capital authority.")}</span>
    </div>
  );
}

export function EmptyState({ title, detail }: { title: string; detail: string }) {
  const { t } = useWorkbenchI18n();
  return (
    <div className="empty-state">
      <Boxes size={34} />
      <h3>{t(title)}</h3>
      <p>{t(detail)}</p>
    </div>
  );
}

export function LoadingState({ label = "Loading evidence" }: { label?: string }) {
  const { t } = useWorkbenchI18n();
  return (
    <div className="loading-state">
      <div className="spinner" />
      <span>{t(label)}</span>
    </div>
  );
}

export function ErrorState({ error }: { error: unknown }) {
  const { t } = useWorkbenchI18n();
  return (
    <div className="error-state">
      <strong>{t("Evidence could not be loaded")}</strong>
      <p>{error instanceof Error ? error.message : String(error)}</p>
    </div>
  );
}

export function WorkspaceShell({ children }: { children: React.ReactNode }) {
  const { t } = useWorkbenchI18n();
  return (
    <div className="workspace-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">FA</div>
          <div>
            <strong>FinAgent</strong>
            <span>{t("Evidence Workspace")}</span>
          </div>
        </div>
        <nav>
          <NavLink to="/" end><LayoutDashboard size={17} /> {t("Cockpit")}</NavLink>
          <NavLink to="/research"><ShieldCheck size={17} /> {t("Research")}</NavLink>
          <NavLink to="/portfolio"><Activity size={17} /> {t("Portfolio")}</NavLink>
          <NavLink to="/governance"><Network size={17} /> {t("Governance")}</NavLink>
          <NavLink to="/reserve"><LockKeyhole size={17} /> {t("Reserve")}</NavLink>
          <NavLink to="/agent"><Boxes size={17} /> {t("Agent Runs")}</NavLink>
          <NavLink to="/widgets"><Search size={17} /> {t("Widget Catalog")}</NavLink>
        </nav>
        <div className="sidebar-footer"><GitBranch size={15} /><span>A5-4 · reserve evidence</span></div>
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
  const { t } = useWorkbenchI18n();
  const stableColumns = useMemo(() => columns, [columns]);
  const table = useReactTable({ data, columns: stableColumns, getCoreRowModel: getCoreRowModel() });
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
                    : typeof header.column.columnDef.header === "string"
                      ? t(header.column.columnDef.header)
                      : flexRender(header.column.columnDef.header, header.getContext())}
                </th>
              ))}
            </tr>
          ))}
        </thead>
        <tbody>
          {table.getRowModel().rows.map((row) => (
            <tr key={row.id} className={onRowClick ? "clickable" : ""} onClick={() => onRowClick?.(row.original)}>
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
  const { t } = useWorkbenchI18n();
  return (
    <header className="page-header">
      <div>
        <span className="eyebrow">{t(eyebrow)}</span>
        <h1>{t(title)}</h1>
        <p>{t(description)}</p>
      </div>
      {children ? <div className="page-actions">{children}</div> : null}
    </header>
  );
}
