import { useEffect, useMemo, useState } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { Download, ExternalLink, LockKeyhole, ShieldCheck } from "lucide-react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { workspaceApi } from "./api";
import { DrawdownChart, LineageDiagram, NavChart } from "./charts";
import {
  EmptyState,
  ErrorState,
  EvidenceTable,
  LoadingState,
  MetricCard,
  PageHeader,
  Panel,
  StatusBadge,
  AuthorityBadge,
} from "./components";
import {
  AttributionBar,
  ExecutionLifecycleChart,
  FoldEvidenceHeatmap,
  RollingEvidenceChart,
  StatisticalForestChart,
  TargetRealizedChart,
} from "./v2Charts";
import type {
  GateRow,
  GovernanceResponse,
  PortfolioCockpitResponse,
  ProgramCockpitResponse,
  ProtocolDiffResponse,
  StatisticalEvidence,
  WorkspaceProject,
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

function pct(value: number | undefined, digits = 2) {
  return `${((value ?? 0) * 100).toFixed(digits)}%`;
}

function num(value: number | undefined, digits = 3) {
  return (value ?? 0).toFixed(digits);
}

function Lifecycle({ project }: { project: WorkspaceProject }) {
  return (
    <div className="lifecycle-rail">
      {project.lifecycle.map((stage) => (
        <div key={stage.stage} className={`lifecycle-stage lifecycle-${stage.status}`}>
          <span className="lifecycle-code">{stage.stage}</span>
          <strong>{stage.label}</strong>
          <span>{stage.status}</span>
          <AuthorityBadge value={stage.authority} />
        </div>
      ))}
    </div>
  );
}

export function ProjectCockpitPage() {
  const navigate = useNavigate();
  const { data, error, loading } = useAsync(workspaceApi.projectsV2, []);
  const columns = useMemo<ColumnDef<WorkspaceProject, unknown>[]>(
    () => [
      { header: "Program", accessorKey: "program_id" },
      { header: "Research", accessorKey: "research_status", cell: ({ row }) => <StatusBadge value={row.original.research_status} /> },
      { header: "A3", accessorKey: "a3_status", cell: ({ row }) => <StatusBadge value={row.original.a3_status} tone="neutral" /> },
      { header: "A4", accessorKey: "a4_status", cell: ({ row }) => <StatusBadge value={row.original.a4_status} /> },
      { header: "Reserve", cell: ({ row }) => <StatusBadge value={String(row.original.reserve.status ?? "unknown")} /> },
      { header: "A5", accessorKey: "a5_status", cell: ({ row }) => <StatusBadge value={row.original.a5_status} tone="neutral" /> },
      { header: "Data", accessorKey: "data_version" },
    ],
    [],
  );
  if (loading) return <LoadingState label="Loading governed projects" />;
  if (error) return <ErrorState error={error} />;
  const projects = data?.items ?? [];
  return (
    <div className="page">
      <PageHeader
        eyebrow="Visualization V2"
        title="Research governance cockpit"
        description="Human-review surface for frozen A2.6 research, A4 execution-aware evidence and the locked one-shot reserve boundary."
      />
      <div className="metric-grid four">
        <MetricCard label="Research programs" value={String(projects.length)} />
        <MetricCard label="Frozen protocols" value={String(projects.filter((item) => item.protocol_frozen).length)} />
        <MetricCard label="A4 validations" value={String(projects.filter((item) => item.a4_validation_id).length)} />
        <MetricCard label="Reserve untouched" value={String(projects.filter((item) => item.reserve.status === "untouched").length)} detail="Required before A5" />
      </div>
      {projects.map((project) => (
        <Panel
          key={project.project_id}
          title={project.program_id || project.program_evidence_id || project.project_id}
          subtitle={`${project.program_spec_id || "source spec unavailable"} · ${project.data_version}`}
          actions={
            <div className="panel-actions">
              {project.program_id ? <Link className="button secondary" to={`/program/${encodeURIComponent(project.program_id)}`}>Research</Link> : null}
              {project.a4_validation_id ? <Link className="button secondary" to={`/portfolio/${encodeURIComponent(project.a4_validation_id)}`}>A4</Link> : null}
              <Link className="button secondary" to={`/governance/${encodeURIComponent(project.a4_validation_id || project.program_evidence_id)}`}>Governance</Link>
            </div>
          }
        >
          {project.lifecycle.length ? <Lifecycle project={project} /> : <p className="subtle">Source A2.6 evidence is not loaded; A4 remains visible as orphan evidence.</p>}
          <div className="identity-strip cockpit-strip">
            <StatusBadge value={project.system_status} />
            <StatusBadge value={project.research_status} />
            <StatusBadge value={`reserve:${String(project.reserve.status ?? "unknown")}`} />
            <AuthorityBadge value="authoritative" />
            <span className="mono">selection:{project.selection_id || "n/a"}</span>
          </div>
          {project.warning ? <p className="warning-copy">{project.warning}</p> : null}
        </Panel>
      ))}
      <Panel title="Project index" subtitle="Select a row to open the governed research lifecycle.">
        {projects.length ? (
          <EvidenceTable
            data={projects}
            columns={columns}
            onRowClick={(project) => {
              if (project.program_id) navigate(`/program/${encodeURIComponent(project.program_id)}`);
              else if (project.a4_validation_id) navigate(`/portfolio/${encodeURIComponent(project.a4_validation_id)}`);
            }}
          />
        ) : (
          <EmptyState title="No governed projects" detail="Configure A2.6/A4 report roots and restart the Workspace." />
        )}
      </Panel>
    </div>
  );
}

function GateMatrix({ items }: { items: GateRow[] }) {
  const criteria = items[0]?.checks.map((check) => check.criterion) ?? [];
  return (
    <div className="gate-matrix-wrap">
      <table className="gate-matrix">
        <thead>
          <tr><th>Factor</th><th>Gate</th>{criteria.map((criterion) => <th key={criterion}>{criterion}</th>)}</tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.feature_digest}>
              <td><strong>{item.feature_id}</strong><span className="mono">{item.feature_digest.slice(0, 16)}…</span></td>
              <td><StatusBadge value={item.passed ? "PASS" : "FAIL"} /></td>
              {item.checks.map((check) => (
                <td key={check.criterion} title={`${check.metric_key} ${check.operator} ${check.threshold ?? "n/a"}`}>
                  <span className={`gate-cell ${check.passed === null ? "gate-na" : check.passed ? "gate-pass" : "gate-fail"}`}>
                    {check.passed === null ? "—" : check.passed ? "✓" : "×"}
                  </span>
                  <small>{num(check.metric, 3)}</small>
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function ProgramCockpitPage() {
  const { programId = "" } = useParams();
  const decoded = decodeURIComponent(programId);
  const { data, error, loading } = useAsync(() => workspaceApi.programCockpitV2(decoded), [decoded]);
  if (loading) return <LoadingState label="Loading ResearchProgram evidence" />;
  if (error) return <ErrorState error={error} />;
  const program = data as ProgramCockpitResponse;
  const statisticalColumns = [
    { header: "Factor", accessorKey: "feature_id" },
    { header: "Effect", accessorKey: "effect", cell: ({ row }: any) => num(row.original.effect, 4) },
    { header: "Bootstrap CI", cell: ({ row }: any) => `[${num(row.original.bootstrap_ci_lower, 4)}, ${num(row.original.bootstrap_ci_upper, 4)}]` },
    { header: "HAC p", accessorKey: "hac_pvalue", cell: ({ row }: any) => num(row.original.hac_pvalue, 4) },
    { header: "Bootstrap p", accessorKey: "bootstrap_pvalue", cell: ({ row }: any) => num(row.original.bootstrap_pvalue, 4) },
    { header: "Holm", accessorKey: "holm_pvalue", cell: ({ row }: any) => num(row.original.holm_pvalue, 4) },
    { header: "BH q", accessorKey: "bh_qvalue", cell: ({ row }: any) => num(row.original.bh_qvalue, 4) },
  ] as ColumnDef<StatisticalEvidence, unknown>[];
  return (
    <div className="page">
      <PageHeader eyebrow="A2.6 ResearchProgram" title={program.program_id} description={program.evidence_id}>
        <Link className="button secondary" to={`/governance/${encodeURIComponent(program.evidence_id)}`}><ShieldCheck size={15} /> Governance</Link>
      </PageHeader>
      <div className="identity-strip">
        <StatusBadge value={program.system_status} />
        <StatusBadge value={program.research_status} />
        <StatusBadge value={`reserve:${String(program.reserve.status ?? "unknown")}`} />
        <AuthorityBadge value="authoritative" />
      </div>
      <Panel title="Frozen protocol identity" subtitle="Identity-bound configuration; outcomes are not part of protocol comparison.">
        <dl className="identity-grid">
          {Object.entries(program.identity).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{String(value ?? "—")}</dd></div>)}
        </dl>
      </Panel>
      <Panel title="Preregistered Gate Matrix" subtitle="Overall Gate decisions are authoritative; per-criterion cells are deterministic presentation checks over frozen thresholds.">
        <GateMatrix items={program.gate_matrix.items} />
      </Panel>
      <div className="two-column">
        <Panel title="Statistical forest" subtitle="Pooled RankIC with bootstrap confidence interval and multiplicity-aware evidence.">
          <StatisticalForestChart items={program.statistics.items} />
        </Panel>
        <Panel title="Statistical evidence table" subtitle="HAC, block bootstrap, Holm and BH are projected from FinAgent core evidence.">
          <EvidenceTable data={program.statistics.items} columns={statisticalColumns} />
        </Panel>
      </div>
      <Panel title="Fold evidence heatmap" subtitle="Test RankICIR by candidate and walk-forward fold. Direction, coverage and turnover remain available in tooltips.">
        <FoldEvidenceHeatmap items={program.fold_evidence.items} foldIds={program.fold_evidence.fold_ids} />
      </Panel>
    </div>
  );
}

export function PortfolioCockpitPage() {
  const { validationId = "" } = useParams();
  const decoded = decodeURIComponent(validationId);
  const { data, error, loading } = useAsync(() => workspaceApi.portfolioCockpitV2(decoded), [decoded]);
  if (loading) return <LoadingState label="Loading A4 portfolio evidence" />;
  if (error) return <ErrorState error={error} />;
  const portfolio = data as PortfolioCockpitResponse;
  if (portfolio.no_portfolio || !portfolio.metrics) {
    return <EmptyState title="No portfolio aggregate" detail="The A4 evidence completed without an aggregate portfolio result." />;
  }
  const metrics = portfolio.metrics as Record<string, number>;
  const points = (portfolio.nav_series ?? []).map((point) => ({
    ...point,
    fees: 0,
    slippage: 0,
    one_way_turnover: 0,
    implementation_shortfall: 0,
    maximum_ex_post_participation: 0,
    desired_order_count: 0,
    order_count: 0,
    fill_count: 0,
    rejected_order_count: 0,
    cash_fallback: false,
  }));
  return (
    <div className="page">
      <PageHeader eyebrow="A4 Portfolio Validation" title={decoded} description="Execution-aware economic evidence before one-shot reserve use.">
        <Link className="button secondary" to={`/execution/${encodeURIComponent(decoded)}`}>Execution <ExternalLink size={14} /></Link>
        <Link className="button secondary" to={`/governance/${encodeURIComponent(decoded)}`}><ShieldCheck size={14} /> Governance</Link>
        <a className="button secondary" href={`/api/v2/a4/${encodeURIComponent(decoded)}/review-bundle`}><Download size={14} /> Review bundle</a>
      </PageHeader>
      <div className="identity-strip">
        <StatusBadge value={portfolio.status} />
        <StatusBadge value={`reserve:${String(portfolio.reserve.status ?? "unknown")}`} />
        <AuthorityBadge value="authoritative" />
      </div>
      <div className="metric-grid six">
        <MetricCard label="Net return" value={pct(metrics.net_return)} />
        <MetricCard label="Gross return" value={pct(metrics.gross_return)} />
        <MetricCard label="Net Sharpe" value={num(metrics.net_sharpe)} />
        <MetricCard label="Max drawdown" value={pct(metrics.max_drawdown)} />
        <MetricCard label="Gross → net drag" value={pct(metrics.gross_to_net_drag)} />
        <MetricCard label="Implementation shortfall" value={pct(metrics.implementation_shortfall)} />
      </div>
      <div className="metric-grid four">
        <MetricCard label="One-way turnover" value={num(metrics.one_way_turnover)} />
        <MetricCard label="Cash fallback" value={pct(metrics.cash_fallback_ratio)} />
        <MetricCard label="Rejected orders" value={pct(metrics.rejected_order_ratio)} />
        <MetricCard label="Max participation" value={pct(metrics.maximum_ex_post_participation)} />
      </div>
      <div className="two-column">
        <Panel title="Gross / net NAV" subtitle="Authoritative A4 account series."><NavChart points={points} /></Panel>
        <Panel title="Drawdown" subtitle="Deterministically derived from authoritative NAV; explicitly non-authoritative.">
          <div className="derived-note">DERIVED PRESENTATION SERIES</div>
          <DrawdownChart points={points} />
        </Panel>
      </div>
      <Panel title="Rolling review series" subtitle={`Derived ${portfolio.derived_rolling?.window ?? 20}-period return, volatility and Sharpe; not new core evidence.`}>
        <div className="derived-note">DERIVED PRESENTATION SERIES</div>
        <RollingEvidenceChart items={portfolio.derived_rolling?.items ?? []} />
      </Panel>
      <Panel title="Walk-forward economic evidence" subtitle="Fold boundaries, costs and implementation shortfall remain authoritative.">
        <pre className="json-view">{JSON.stringify(portfolio.folds ?? [], null, 2)}</pre>
      </Panel>
      <Panel title="Statistical/economic gate evidence"><pre className="json-view">{JSON.stringify(portfolio.economic_evidence ?? {}, null, 2)}</pre></Panel>
    </div>
  );
}

export function ExecutionCockpitPage() {
  const { validationId = "" } = useParams();
  const decoded = decodeURIComponent(validationId);
  const { data, error, loading } = useAsync(() => workspaceApi.executionCockpitV2(decoded), [decoded]);
  if (loading) return <LoadingState label="Loading immutable execution ledger" />;
  if (error) return <ErrorState error={error} />;
  if (!data) return null;
  const execution = data;
  const driftColumns = [
    { header: "Date", accessorKey: "session_date" },
    { header: "Asset", accessorKey: "asset" },
    { header: "Target", accessorKey: "target_weight", cell: ({ row }: any) => pct(row.original.target_weight) },
    { header: "Realized", accessorKey: "realized_weight", cell: ({ row }: any) => pct(row.original.realized_weight) },
    { header: "Drift", accessorKey: "drift", cell: ({ row }: any) => pct(row.original.drift) },
  ] as ColumnDef<(typeof execution.target_vs_realized.items)[number], unknown>[];
  return (
    <div className="page">
      <PageHeader eyebrow="A3 → A4 Execution" title="Execution realization cockpit" description={decoded}>
        <Link className="button secondary" to={`/portfolio/${encodeURIComponent(decoded)}`}>Portfolio</Link>
        <Link className="button secondary" to={`/governance/${encodeURIComponent(decoded)}`}>Governance</Link>
      </PageHeader>
      <div className="identity-strip">
        <StatusBadge value={`reserve:${execution.reserve_status}`} />
        <AuthorityBadge value="authoritative" />
        <span className="mono">ledger:{String(execution.ledger.digest ?? "n/a")}</span>
      </div>
      <div className="two-column">
        <Panel title="Desired → decision → fill" subtitle={execution.funnel.note}><ExecutionLifecycleChart execution={execution} /></Panel>
        <Panel title="Constraint attribution" subtitle="T+1, lot, suspension, price-limit, cash and session/data reasons."><AttributionBar values={execution.reason_categories} /></Panel>
      </div>
      <div className="two-column">
        <Panel title="Cost attribution" subtitle={execution.costs.component_detail_available ? "Fee breakdown is summed from immutable fill records." : "Only A4 aggregate costs are available."}>
          <AttributionBar values={execution.costs.components} label="CNY / cost units" />
        </Panel>
        <Panel title="Decision status"><AttributionBar values={execution.decision_status_counts} /></Panel>
      </div>
      <Panel title="Target vs realized" subtitle={execution.target_vs_realized.definition}>
        <div className="derived-note">DERIVED REALIZED WEIGHTS</div>
        {execution.target_vs_realized.items.length ? <TargetRealizedChart items={execution.target_vs_realized.items} /> : <EmptyState title="No target/close-state rows" detail="A matching immutable A4 ledger is required." />}
        {execution.target_vs_realized.items.length ? <EvidenceTable data={execution.target_vs_realized.items} columns={driftColumns} /> : null}
      </Panel>
      <Panel title="Session lifecycle records" subtitle="Canonical A3 compilation and exchange realization projected from A4 JSONL.">
        <pre className="json-view">{JSON.stringify(execution.sessions, null, 2)}</pre>
      </Panel>
    </div>
  );
}

function ProtocolDiffPanel({ source, target }: { source: string; target: string }) {
  const { data, error, loading } = useAsync(() => workspaceApi.protocolDiffV2(source, target), [source, target]);
  if (loading) return <LoadingState label="Comparing frozen protocols" />;
  if (error) return <ErrorState error={error} />;
  const diff = data as ProtocolDiffResponse;
  const changed = diff.changes.filter((item) => item.changed);
  return (
    <Panel title="Protocol comparison" subtitle={`${diff.changed_count} deterministic differences; outcomes are intentionally excluded.`}>
      <div className="derived-note">DERIVED CONFIGURATION DIFF</div>
      <div className="protocol-diff-list">
        {changed.map((item) => (
          <div key={item.field} className="protocol-diff-row">
            <strong>{item.field}</strong>
            <code>{JSON.stringify(item.left)}</code>
            <span>→</span>
            <code>{JSON.stringify(item.right)}</code>
          </div>
        ))}
      </div>
    </Panel>
  );
}

export function GovernancePage() {
  const { evidenceId = "" } = useParams();
  const decoded = decodeURIComponent(evidenceId);
  const governanceState = useAsync(() => workspaceApi.governanceV2(decoded), [decoded]);
  const rawState = useAsync(() => workspaceApi.rawEvidenceV2(decoded), [decoded]);
  if (governanceState.loading) return <LoadingState label="Loading lineage and protocol identity" />;
  if (governanceState.error) return <ErrorState error={governanceState.error} />;
  const governance = governanceState.data as GovernanceResponse;
  return (
    <div className="page">
      <PageHeader eyebrow="Governance" title="Immutable evidence lineage" description={decoded} />
      <div className="identity-strip">
        <StatusBadge value={`reserve:${governance.reserve_status}`} />
        <StatusBadge value={`promotion:${governance.promotion_eligible ? "eligible" : "not-eligible"}`} tone="neutral" />
        <AuthorityBadge value="authoritative" />
      </div>
      <Panel title="A2.6 → A4 lineage" subtitle="Only persisted immutable evidence identities appear in the authoritative DAG.">
        <LineageDiagram graph={governance.lineage} />
      </Panel>
      {governance.a3_protocol_binding ? (
        <Panel title="A3 protocol binding" subtitle="Execution semantics are bound by A4 but no standalone authoritative A3 certification ID is persisted.">
          <div className="identity-strip"><AuthorityBadge value={governance.a3_protocol_binding.authority} /><span className="mono">{governance.a3_protocol_binding.binding_id}</span></div>
          <p className="subtle">{governance.a3_protocol_binding.note}</p>
          <pre className="json-view">{JSON.stringify(governance.a3_protocol_binding.payload, null, 2)}</pre>
        </Panel>
      ) : null}
      {governance.source_program_evidence_id && governance.source_program_evidence_id !== decoded ? (
        <ProtocolDiffPanel source={governance.source_program_evidence_id} target={decoded} />
      ) : null}
      <Panel title="Protocol snapshot" subtitle="Allowlisted frozen configuration only; research outcomes are excluded from diff semantics.">
        <pre className="json-view">{JSON.stringify(governance.protocol, null, 2)}</pre>
      </Panel>
      <Panel title="Raw evidence inspector" subtitle="Read-only source payload for audit. No mutation control is exposed.">
        {rawState.loading ? <LoadingState /> : rawState.error ? <ErrorState error={rawState.error} /> : <details><summary>Open immutable report payload</summary><pre className="json-view raw-inspector">{JSON.stringify(rawState.data, null, 2)}</pre></details>}
      </Panel>
    </div>
  );
}

export function GovernanceIndexPage() {
  const { data, error, loading } = useAsync(workspaceApi.projectsV2, []);
  if (loading) return <LoadingState />;
  if (error) return <ErrorState error={error} />;
  const projects = data?.items ?? [];
  return (
    <div className="page">
      <PageHeader eyebrow="Governance" title="Protocol review queue" description="Open the most advanced immutable evidence for each governed ResearchProgram." />
      <div className="widget-grid">
        {projects.map((project) => {
          const evidence = project.a4_validation_id || project.program_evidence_id;
          return (
            <article key={project.project_id} className="widget-card">
              <div className="widget-top"><StatusBadge value={String(project.reserve.status ?? "unknown")} /><AuthorityBadge value="authoritative" /></div>
              <h3>{project.program_id || project.project_id}</h3>
              <p>{project.a4_status || project.research_status}</p>
              <Link className="inline-link" to={`/governance/${encodeURIComponent(evidence)}`}><LockKeyhole size={14} /> Open governance review</Link>
            </article>
          );
        })}
      </div>
    </div>
  );
}
