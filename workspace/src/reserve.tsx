import { useEffect, useMemo, useState } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { ExternalLink, LockKeyhole, ShieldCheck } from "lucide-react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { workspaceApi } from "./api";
import { LineageDiagram } from "./charts";
import {
  AuthorityBadge,
  EmptyState,
  ErrorState,
  EvidenceTable,
  LoadingState,
  MetricCard,
  PageHeader,
  Panel,
  StatusBadge,
} from "./components";
import type {
  ReserveLedgerResponse,
  ReserveLifecycleResponse,
  ReserveListResponse,
} from "./types";

function useAsync<T>(loader: () => Promise<T>, dependencies: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    loader()
      .then((value) => active && setData(value))
      .catch((reason: unknown) => active && setError(reason))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, dependencies);
  return { data, error, loading };
}

function nestedNumber(value: unknown, path: string[]): number | null {
  let current: unknown = value;
  for (const key of path) {
    if (!current || typeof current !== "object") return null;
    current = (current as Record<string, unknown>)[key];
  }
  return typeof current === "number" && Number.isFinite(current) ? current : null;
}

function pct(value: number | null, digits = 2) {
  return value === null ? "—" : `${(value * 100).toFixed(digits)}%`;
}

function num(value: number | null, digits = 3) {
  return value === null ? "—" : value.toFixed(digits);
}

function ReserveLifecycleRail({ reserve }: { reserve: ReserveLifecycleResponse }) {
  const stages = [
    { code: "A5-1", label: "Eligibility seal", value: reserve.seal, status: reserve.seal ? "complete" : "pending" },
    { code: "A5-3", label: "Durable CONSUMED claim", value: reserve.claim, status: reserve.claim ? "complete" : "pending" },
    { code: "A5-2", label: "Terminal result", value: reserve.terminal, status: reserve.terminal ? String(reserve.terminal.status ?? "complete") : "pending" },
    { code: "A5-3", label: "Replay audit", value: reserve.audit, status: reserve.audit ? "verified" : reserve.claim ? "pending" : "locked" },
  ];
  return (
    <div className="lifecycle-rail reserve-lifecycle-rail">
      {stages.map((stage, index) => (
        <div key={`${stage.code}-${index}`} className={`lifecycle-stage lifecycle-${stage.status.toLowerCase()}`}>
          <span className="lifecycle-code">{stage.code}</span>
          <strong>{stage.label}</strong>
          <span>{stage.status}</span>
          <AuthorityBadge value={stage.value ? "authoritative" : "derived"} />
        </div>
      ))}
    </div>
  );
}

export function ReserveIndexPage() {
  const navigate = useNavigate();
  const { data, error, loading } = useAsync(workspaceApi.reservesV2, []);
  const payload = data as ReserveListResponse | null;
  const items = payload?.items ?? [];
  const columns = useMemo<ColumnDef<ReserveLifecycleResponse, unknown>[]>(
    () => [
      { header: "Reserve", accessorKey: "reserve_id" },
      { header: "State", accessorKey: "state", cell: ({ row }) => <StatusBadge value={row.original.state} /> },
      { header: "Terminal", accessorKey: "a5_status", cell: ({ row }) => <StatusBadge value={row.original.a5_status} /> },
      { header: "Integrity", cell: ({ row }) => <StatusBadge value={row.original.integrity.status} /> },
      { header: "Ledger", cell: ({ row }) => row.original.ledger.available ? `${row.original.ledger.row_count} rows` : "—" },
      { header: "A4", accessorKey: "portfolio_validation_id" },
    ],
    [],
  );
  if (loading) return <LoadingState label="Loading A5 reserve evidence" />;
  if (error) return <ErrorState error={error} />;
  return (
    <div className="page">
      <PageHeader
        eyebrow="A5-4 Workspace"
        title="Reserve evidence cockpit"
        description="Read-only projection of eligibility, irreversible CONSUMED state, terminal evidence, immutable ledger and replay audit."
      />
      <div className="metric-grid four">
        <MetricCard label="Reserve identities" value={String(items.length)} />
        <MetricCard label="Consumed" value={String(items.filter((item) => item.state === "CONSUMED").length)} />
        <MetricCard label="Terminal PASS" value={String(items.filter((item) => item.a5_status === "RESERVE_PASS").length)} />
        <MetricCard label="Fully audited" value={String(items.filter((item) => item.integrity.fully_audited).length)} />
      </div>
      {!payload?.configured ? (
        <EmptyState title="A5 lifecycle stores are not configured" detail="Start Workspace with the A5 eligibility, consumption and terminal SQLite stores to inspect one-shot reserve evidence." />
      ) : null}
      {(payload?.warnings ?? []).length ? (
        <Panel title="Reserve store warnings" subtitle="Configured A5 evidence stores are missing or unavailable.">
          <ul className="warning-list">{payload?.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>
        </Panel>
      ) : null}
      {items.length ? (
        <Panel title="One-shot reserve identities" subtitle="Select a reserve to inspect the authoritative A5 lifecycle.">
          <EvidenceTable data={items} columns={columns} onRowClick={(item) => navigate(`/reserve/${encodeURIComponent(item.reserve_id)}`)} />
        </Panel>
      ) : payload?.configured ? (
        <EmptyState title="No A5 evidence" detail="Configured stores contain no persisted eligibility or consumption lifecycle yet." />
      ) : null}
    </div>
  );
}

function ReserveLedgerPanel({ reserveId }: { reserveId: string }) {
  const { data, error, loading } = useAsync(() => workspaceApi.reserveLedgerV2(reserveId), [reserveId]);
  if (loading) return <LoadingState label="Loading immutable reserve ledger" />;
  if (error) return <ErrorState error={error} />;
  const ledger = data as ReserveLedgerResponse;
  return (
    <>
      <div className="identity-strip">
        <AuthorityBadge value="authoritative" />
        <span className="mono">rows:{ledger.row_count}</span>
        <span className="mono">sha256:{ledger.file_sha256}</span>
      </div>
      <details>
        <summary>Open canonical reserve ledger rows</summary>
        <pre className="json-view raw-inspector">{JSON.stringify(ledger.rows, null, 2)}</pre>
      </details>
    </>
  );
}

export function ReserveDetailPage() {
  const { reserveId = "" } = useParams();
  const decoded = decodeURIComponent(reserveId);
  const { data, error, loading } = useAsync(() => workspaceApi.reserveV2(decoded), [decoded]);
  if (loading) return <LoadingState label="Loading authoritative A5 lifecycle" />;
  if (error) return <ErrorState error={error} />;
  const reserve = data as ReserveLifecycleResponse;
  const terminal = reserve.terminal;
  const aggregate = terminal?.aggregate;
  const netReturn = nestedNumber(aggregate, ["net_metrics", "total_return"]);
  const grossReturn = nestedNumber(aggregate, ["gross_metrics", "total_return"]);
  const netSharpe = nestedNumber(aggregate, ["net_metrics", "sharpe"]);
  const maxDrawdown = nestedNumber(aggregate, ["net_metrics", "max_drawdown"]);
  const reasonCodes = Array.isArray(terminal?.reason_codes) ? terminal.reason_codes : [];
  const checks = reserve.integrity.checks;
  const checkColumns = [
    { header: "Check", accessorKey: "name" },
    { header: "Status", cell: ({ row }: any) => <StatusBadge value={row.original.passed ? "PASS" : "FAIL"} /> },
    { header: "Meaning", accessorKey: "detail" },
  ] as ColumnDef<(typeof checks)[number], unknown>[];
  return (
    <div className="page">
      <PageHeader eyebrow="A5 One-shot Reserve" title={decoded} description="Immutable post-reserve evidence. This page exposes no retry, threshold, promotion or order controls.">
        {reserve.portfolio_validation_id ? <Link className="button secondary" to={`/portfolio/${encodeURIComponent(reserve.portfolio_validation_id)}`}>A4 Portfolio <ExternalLink size={14} /></Link> : null}
        {reserve.portfolio_validation_id ? <Link className="button secondary" to={`/governance/${encodeURIComponent(reserve.portfolio_validation_id)}`}><ShieldCheck size={14} /> Governance</Link> : null}
      </PageHeader>
      <div className="identity-strip">
        <StatusBadge value={`state:${reserve.state}`} />
        <StatusBadge value={reserve.a5_status} />
        <StatusBadge value={`integrity:${reserve.integrity.status}`} />
        <AuthorityBadge value="authoritative" />
        {reserve.claim ? <span className="mono">retry:false</span> : null}
      </div>
      <ReserveLifecycleRail reserve={reserve} />
      <div className="metric-grid four">
        <MetricCard label="Net return" value={pct(netReturn)} />
        <MetricCard label="Gross return" value={pct(grossReturn)} />
        <MetricCard label="Net Sharpe" value={num(netSharpe)} />
        <MetricCard label="Max drawdown" value={pct(maxDrawdown)} />
      </div>
      <div className="two-column">
        <Panel title="A5 lineage" subtitle="Persisted authoritative identities from reviewed seal through replay audit.">
          <LineageDiagram graph={reserve.lineage} />
        </Panel>
        <Panel title="Terminal decision" subtitle="Reserve failure is a legal terminal result and never enables an automatic retry.">
          {terminal ? (
            <>
              <div className="identity-strip">
                <StatusBadge value={String(terminal.status ?? reserve.a5_status)} />
                <StatusBadge value={terminal.error_type ? "execution-failure" : "economic-terminal"} tone="neutral" />
              </div>
              <div className="reason-list">{reasonCodes.map((code) => <StatusBadge key={code} value={code} tone="neutral" />)}</div>
              {terminal.error_type ? <p className="warning-copy">{String(terminal.error_type)}: {String(terminal.error_message ?? "")}</p> : null}
            </>
          ) : (
            <EmptyState title="No terminal evidence" detail={reserve.state === "CONSUMED" ? "The reserve is already CONSUMED. Use the explicit no-reaccess recovery path outside Workspace; this UI cannot retry it." : "Reserve has not been executed."} />
          )}
        </Panel>
      </div>
      <Panel title="Lifecycle integrity" subtitle="Every check is recomputed read-only from persisted claim, terminal, ledger and audit identities.">
        <EvidenceTable data={checks} columns={checkColumns} />
      </Panel>
      <Panel title="Immutable reserve ledger" subtitle="Exact terminal ledger bytes are available only for completed economic evaluations.">
        {reserve.ledger.available ? <ReserveLedgerPanel reserveId={decoded} /> : <EmptyState title="No completed reserve ledger" detail={terminal?.error_type ? "Execution-failure terminal evidence correctly carries no completed ledger." : "No terminal ledger has been persisted."} />}
      </Panel>
      <Panel title="Raw A5 evidence inspector" subtitle="Identity-bound payloads only; no mutation controls are exposed.">
        <details><summary><LockKeyhole size={13} /> Open seal / claim / terminal / audit payloads</summary><pre className="json-view raw-inspector">{JSON.stringify({ seal: reserve.seal, claim: reserve.claim, terminal: reserve.terminal, audit: reserve.audit }, null, 2)}</pre></details>
      </Panel>
    </div>
  );
}
