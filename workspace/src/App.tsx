import { useEffect, useMemo, useState } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { ArrowLeft, ExternalLink, FileWarning, Search } from "lucide-react";
import {
  BrowserRouter,
  Link,
  Navigate,
  Route,
  Routes,
  useNavigate,
  useParams,
} from "react-router-dom";

import { workspaceApi } from "./api";
import {
  DrawdownChart,
  ExecutionFunnel,
  FactorEvidenceChart,
  LineageDiagram,
  NavChart,
  RejectionChart,
} from "./charts";
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
import { ReserveDetailPage, ReserveIndexPage } from "./reserve";
import {
  ExecutionCockpitPage,
  GovernanceIndexPage,
  GovernancePage,
  PortfolioCockpitPage,
  ProgramCockpitPage,
  ProjectCockpitPage,
} from "./v2";
import { AgentWorkbenchPage, LegacyAgentRunRedirect } from "./workbench/agent";
import { FactorTearSheetPage } from "./workbench/factors";
import { WorkbenchReferencePage } from "./workbench/reference";
import { WorkbenchProviders, WorkbenchShell } from "./workbench/shell";
import { StrategyDecisionExplorerPage } from "./workbench/strategy";
import "./workbench/workbench.css";

import type {
  CatalogItem,
  CatalogResponse,
  EvidenceBundle,
  FactorEvidence,
  FactorOccurrence,
  WidgetSpec,
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
      .then((value) => {
        if (active) setData(value);
      })
      .catch((reason: unknown) => {
        if (active) setError(reason);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
    // The V0-V2 compatibility pages keep their frozen loader behavior. New V3
    // Workbench resources use the shared query layer under workbench/query.tsx.
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

function CatalogView({
  title,
  description,
  predicate,
}: {
  title: string;
  description: string;
  predicate?: (item: CatalogItem) => boolean;
}) {
  const navigate = useNavigate();
  const { data, error, loading } = useAsync(workspaceApi.catalog, []);
  const [query, setQuery] = useState("");
  const items = useMemo(() => {
    const values = (data?.items ?? []).filter((item) => (predicate ? predicate(item) : true));
    const normalized = query.trim().toLowerCase();
    if (!normalized) return values;
    return values.filter((item) =>
      [
        item.evidence_id,
        item.evidence_type,
        item.program_id,
        item.research_status,
        item.data_version,
      ].some((value) => value.toLowerCase().includes(normalized)),
    );
  }, [data, predicate, query]);
  const columns = useMemo<ColumnDef<CatalogItem, unknown>[]>(
    () => [
      {
        header: "Stage",
        accessorKey: "stage",
        cell: ({ row }) => <span className="mono subtle">{row.original.stage}</span>,
      },
      {
        header: "Evidence",
        accessorKey: "evidence_id",
        cell: ({ row }) => (
          <div className="stacked-cell">
            <strong>{row.original.evidence_type}</strong>
            <span className="mono">{row.original.evidence_id}</span>
          </div>
        ),
      },
      {
        header: "System",
        accessorKey: "system_status",
        cell: ({ row }) => <StatusBadge value={row.original.system_status} />,
      },
      {
        header: "Research",
        accessorKey: "research_status",
        cell: ({ row }) => <StatusBadge value={row.original.research_status} />,
      },
      {
        header: "Reserve",
        accessorKey: "reserve_status",
        cell: ({ row }) => <StatusBadge value={row.original.reserve_status} />,
      },
      {
        header: "Factors",
        accessorKey: "factor_count",
      },
      {
        header: "Authority",
        accessorKey: "authority",
        cell: ({ row }) => <AuthorityBadge value={row.original.authority} />,
      },
    ],
    [],
  );
  if (loading) return <LoadingState />;
  if (error) return <ErrorState error={error} />;
  const catalog = data as CatalogResponse;
  return (
    <div className="page">
      <PageHeader eyebrow="Evidence catalog" title={title} description={description}>
        <label className="search-box">
          <Search size={16} />
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search identity or status" />
        </label>
      </PageHeader>
      <div className="metric-grid four">
        <MetricCard label="Evidence artifacts" value={String(items.length)} />
        <MetricCard
          label="System PASS"
          value={String(items.filter((item) => item.system_status.toUpperCase().includes("PASS")).length)}
        />
        <MetricCard
          label="Reserve untouched"
          value={String(items.filter((item) => item.reserve_status === "untouched").length)}
        />
        <MetricCard
          label="Promotion eligible"
          value={String(items.filter((item) => item.promotion_eligible).length)}
          detail="Expected to remain zero before A5/A6"
        />
      </div>
      {catalog.warnings.length ? (
        <Panel title="Catalog warnings" subtitle="Malformed, unsupported or identity-conflicting files require attention.">
          <ul className="warning-list">
            {catalog.warnings.map((warning) => (
              <li key={warning}><FileWarning size={15} /> {warning}</li>
            ))}
          </ul>
        </Panel>
      ) : null}
      {(catalog.notices ?? []).length ? (
        <Panel title="Catalog notices" subtitle="Equivalent replay files are de-duplicated without removing the authoritative identity.">
          <ul className="notice-list">
            {(catalog.notices ?? []).map((notice) => (
              <li key={notice}><FileWarning size={15} /> {notice}</li>
            ))}
          </ul>
        </Panel>
      ) : null}
      <Panel title="Immutable evidence" subtitle="Select a row to inspect the semantic projection and lineage.">
        {items.length ? (
          <EvidenceTable
            data={items}
            columns={columns}
            onRowClick={(item) => {
              if (item.stage === "a2p6_robust_research" && item.program_id) {
                navigate(`/program/${encodeURIComponent(item.program_id)}`);
              } else if (item.stage === "a4_portfolio_validation") {
                navigate(`/portfolio/${encodeURIComponent(item.evidence_id)}`);
              } else {
                navigate(`/evidence/${encodeURIComponent(item.evidence_id)}`);
              }
            }}
          />
        ) : (
          <EmptyState title="No supported evidence found" detail="Add A2/A2.6/A4 report JSON under a configured report root and restart the Workspace." />
        )}
      </Panel>
    </div>
  );
}

function FactorTable({ factors }: { factors: FactorEvidence[] }) {
  const navigate = useNavigate();
  const columns = useMemo<ColumnDef<FactorEvidence, unknown>[]>(
    () => [
      {
        header: "Factor",
        accessorKey: "feature_id",
        cell: ({ row }) => (
          <div className="stacked-cell">
            <strong>{row.original.feature_id}</strong>
            <span className="mono">{row.original.feature_digest.slice(0, 18)}…</span>
          </div>
        ),
      },
      {
        header: "Gate",
        accessorKey: "status",
        cell: ({ row }) => <StatusBadge value={row.original.status || "candidate"} />,
      },
      {
        header: "Selected",
        accessorKey: "selected",
        cell: ({ row }) => (row.original.selected ? "yes" : "no"),
      },
      {
        header: "Weight",
        accessorKey: "weight",
        cell: ({ row }) => pct(row.original.weight),
      },
      {
        header: "Direction",
        accessorKey: "direction",
      },
      {
        header: "Pooled RankICIR",
        cell: ({ row }) => num(row.original.metrics.pooled_rank_icir ?? row.original.metrics.validation_rank_icir),
      },
      {
        header: "Worst-fold",
        cell: ({ row }) => num(row.original.metrics.worst_fold_rank_icir),
      },
      {
        header: "BH q",
        cell: ({ row }) => num(row.original.metrics.bh_qvalue),
      },
    ],
    [],
  );
  return (
    <EvidenceTable
      data={factors}
      columns={columns}
      onRowClick={(factor) => navigate(`/factor/${encodeURIComponent(factor.feature_digest)}`)}
    />
  );
}

function PortfolioSection({ bundle }: { bundle: EvidenceBundle }) {
  const portfolio = bundle.portfolio;
  const execution = bundle.execution;
  if (!portfolio || !execution) return null;
  const metrics = portfolio.metrics;
  return (
    <>
      <div className="metric-grid six">
        <MetricCard label="Net return" value={pct(metrics.net_total_return)} />
        <MetricCard label="Gross return" value={pct(metrics.gross_total_return)} />
        <MetricCard label="Net Sharpe" value={num(metrics.net_sharpe)} />
        <MetricCard label="Net max drawdown" value={pct(metrics.net_max_drawdown)} />
        <MetricCard label="Cost drag" value={pct(metrics.gross_to_net_return_drag)} />
        <MetricCard label="Rejected orders" value={pct(execution.rejected_order_ratio)} />
      </div>
      <div className="two-column">
        <Panel title="Gross / net NAV" subtitle="Authoritative A4 account series.">
          <NavChart points={portfolio.points} />
        </Panel>
        <Panel title="Drawdown" subtitle="Deterministically derived from authoritative NAV; not a new core metric.">
          <div className="derived-note">DERIVED PRESENTATION SERIES</div>
          <DrawdownChart points={portfolio.points} />
        </Panel>
      </div>
      <div className="two-column">
        <Panel title="Order realization" subtitle="Desired → executable → filled under A3 rules.">
          <ExecutionFunnel execution={execution} />
        </Panel>
        <Panel title="Execution constraints" subtitle="Reason-code attribution from the authoritative execution evidence.">
          {Object.keys(execution.reason_counts).length ? (
            <RejectionChart execution={execution} />
          ) : (
            <EmptyState title="No reason codes" detail="The report contains no execution adjustment or rejection attribution." />
          )}
        </Panel>
      </div>
      <Panel title="Cost and realization diagnostics">
        <div className="metric-grid six">
          <MetricCard label="Fees" value={num(execution.costs.fees, 2)} />
          <MetricCard label="Slippage" value={num(execution.costs.slippage, 2)} />
          <MetricCard label="Cash fallback" value={pct(execution.cash_fallback_ratio)} />
          <MetricCard label="Max participation" value={pct(execution.maximum_ex_post_participation)} />
          <MetricCard label="Desired orders" value={String(execution.desired_order_count)} />
          <MetricCard label="Fills" value={String(execution.fill_count)} />
        </div>
      </Panel>
    </>
  );
}

function EvidencePage() {
  const { evidenceId = "" } = useParams();
  const decoded = decodeURIComponent(evidenceId);
  const { data, error, loading } = useAsync(() => workspaceApi.evidence(decoded), [decoded]);
  if (loading) return <LoadingState />;
  if (error) return <ErrorState error={error} />;
  const bundle = data as EvidenceBundle;
  return (
    <div className="page">
      <PageHeader
        eyebrow={bundle.root.stage}
        title={String(bundle.root.metadata.label ?? bundle.root.evidence_type)}
        description={bundle.root.evidence_id}
      >
        <Link className="button secondary" to="/"><ArrowLeft size={15} /> Catalog</Link>
      </PageHeader>
      <div className="identity-strip">
        <StatusBadge value={bundle.system_status} />
        <StatusBadge value={bundle.research_status} />
        <StatusBadge value={`reserve:${bundle.reserve_status}`} />
        <AuthorityBadge value={bundle.root.authority} />
        <span className="mono">data:{bundle.root.data_version || "n/a"}</span>
      </div>
      {bundle.factors.length ? (
        <>
          <Panel title="Factor family" subtitle="All candidate evidence remains visible; selection does not remove failed trials.">
            <FactorEvidenceChart factors={bundle.factors} />
            <FactorTable factors={bundle.factors} />
          </Panel>
        </>
      ) : null}
      <PortfolioSection bundle={bundle} />
      <Panel title="Evidence lineage" subtitle="Parent → child dependencies over immutable identities.">
        <LineageDiagram graph={bundle.lineage} />
      </Panel>
      <Panel title="Identity and source">
        <dl className="identity-grid">
          <div><dt>Evidence ID</dt><dd>{bundle.root.evidence_id}</dd></div>
          <div><dt>Spec ID</dt><dd>{bundle.root.spec_id || "—"}</dd></div>
          <div><dt>Program ID</dt><dd>{bundle.root.program_id || "—"}</dd></div>
          <div><dt>Schema</dt><dd>{bundle.root.schema_version}</dd></div>
          <div><dt>Artifact digest</dt><dd>{bundle.root.artifact_digest}</dd></div>
          <div><dt>Source URI</dt><dd>{bundle.root.source_uri}</dd></div>
        </dl>
      </Panel>
    </div>
  );
}

function FactorPage() {
  const { digest = "" } = useParams();
  const decoded = decodeURIComponent(digest);
  const { data, error, loading } = useAsync(() => workspaceApi.factor(decoded), [decoded]);
  if (loading) return <LoadingState />;
  if (error) return <ErrorState error={error} />;
  const occurrences = data?.occurrences ?? [];
  return (
    <div className="page">
      <PageHeader eyebrow="Factor evidence" title={occurrences[0]?.factor.feature_id ?? "Factor"} description={decoded}>
        <Link className="button secondary" to="/"><ArrowLeft size={15} /> Catalog</Link>
      </PageHeader>
      {occurrences.map((occurrence: FactorOccurrence) => (
        <Panel
          key={`${occurrence.parent_evidence_id}-${occurrence.factor.feature_digest}`}
          title={occurrence.parent_stage}
          subtitle={occurrence.parent_evidence_id}
          actions={<Link className="inline-link" to={`/evidence/${encodeURIComponent(occurrence.parent_evidence_id)}`}>Open parent <ExternalLink size={14} /></Link>}
        >
          <div className="metric-grid four">
            <MetricCard label="Gate/status" value={occurrence.factor.status || "candidate"} />
            <MetricCard label="Selected" value={occurrence.factor.selected ? "yes" : "no"} />
            <MetricCard label="Weight" value={pct(occurrence.factor.weight)} />
            <MetricCard label="Direction" value={String(occurrence.factor.direction)} />
          </div>
          <p className="hypothesis">{occurrence.factor.hypothesis || "No hypothesis text persisted."}</p>
          {occurrence.factor.reason_codes.length ? (
            <div className="reason-list">{occurrence.factor.reason_codes.map((reason) => <StatusBadge key={reason} value={reason} tone="bad" />)}</div>
          ) : null}
          <pre className="json-view">{JSON.stringify(occurrence.factor.metrics, null, 2)}</pre>
        </Panel>
      ))}
    </div>
  );
}

function WidgetCatalogPage() {
  const { data, error, loading } = useAsync(workspaceApi.widgets, []);
  if (loading) return <LoadingState />;
  if (error) return <ErrorState error={error} />;
  return (
    <div className="page">
      <PageHeader eyebrow="Product contract" title="Widget catalog" description="Widgets are defined by the research question and evidence authority, not only chart type." />
      <div className="widget-grid">
        {(data ?? []).map((widget: WidgetSpec) => (
          <article key={widget.widget_id} className="widget-card">
            <div className="widget-top"><AuthorityBadge value={widget.authority} /><StatusBadge value={widget.surface} tone="neutral" /></div>
            <h3>{widget.widget_id}</h3>
            <p>{widget.question}</p>
            <dl><dt>Renderer</dt><dd>{widget.renderer}</dd><dt>Endpoint</dt><dd className="mono">{widget.data_endpoint}</dd><dt>Link keys</dt><dd>{widget.link_keys.join(", ") || "—"}</dd></dl>
          </article>
        ))}
      </div>
    </div>
  );
}

function NotFoundPage() {
  return <Navigate to="/" replace />;
}

export default function App() {
  return (
    <BrowserRouter>
      <WorkbenchProviders>
        <WorkbenchShell>
          <Routes>
            <Route path="/" element={<ProjectCockpitPage />} />
            <Route path="/catalog" element={<CatalogView title="Evidence catalog" description="V1-compatible immutable evidence index and deep links." />} />
            <Route path="/research" element={<CatalogView title="Research programs" description="A2/A2.5 and A2.6 factor evidence, robust gates and frozen selections." predicate={(item) => !item.has_portfolio} />} />
            <Route path="/program/:programId" element={<ProgramCockpitPage />} />
            <Route path="/portfolio" element={<CatalogView title="Portfolio validations" description="A4 gross/net portfolio, execution and economic evidence." predicate={(item) => item.has_portfolio} />} />
            <Route path="/portfolio/:validationId" element={<PortfolioCockpitPage />} />
            <Route path="/execution/:validationId" element={<ExecutionCockpitPage />} />
            <Route path="/strategy" element={<StrategyDecisionExplorerPage />} />
            <Route path="/strategy/:seriesId" element={<StrategyDecisionExplorerPage />} />
            <Route path="/factors" element={<FactorTearSheetPage />} />
            <Route path="/factors/:seriesId" element={<FactorTearSheetPage />} />
            <Route path="/governance" element={<GovernanceIndexPage />} />
            <Route path="/governance/:evidenceId" element={<GovernancePage />} />
            <Route path="/reserve" element={<ReserveIndexPage />} />
            <Route path="/reserve/:reserveId" element={<ReserveDetailPage />} />
            <Route path="/evidence/:evidenceId" element={<EvidencePage />} />
            <Route path="/factor/:digest" element={<FactorPage />} />
            <Route path="/agent" element={<AgentWorkbenchPage />} />
            <Route path="/agent/:runId" element={<LegacyAgentRunRedirect />} />
            <Route path="/ref/:kind/:identity" element={<WorkbenchReferencePage />} />
            <Route path="/widgets" element={<WidgetCatalogPage />} />
            <Route path="*" element={<NotFoundPage />} />
          </Routes>
        </WorkbenchShell>
      </WorkbenchProviders>
    </BrowserRouter>
  );
}
