import { ExternalLink, FileCode2, Link2, LockKeyhole, Network } from "lucide-react";
import { Link, useParams } from "react-router-dom";

import { workspaceApi } from "../api";
import { ErrorState, LoadingState, StatusBadge } from "../components";
import {
  patchWorkbenchContext,
  useWorkbenchContext,
  workbenchContextSearch,
  type WorkbenchContextKey,
  type WorkbenchContextState,
} from "./context";
import { useWorkbenchQuery } from "./query";
import type {
  WorkbenchReferenceKindV3,
  WorkbenchReferenceSummaryV3,
} from "./types";
import "./reference.css";

const REFERENCE_KINDS = new Set<WorkbenchReferenceKindV3>([
  "evidence",
  "artifact",
  "factor",
  "research_program",
  "portfolio_validation",
  "reserve",
  "agent_run",
  "config_snapshot",
  "config_diff",
  "command_run",
]);

function refKind(value: string): WorkbenchReferenceKindV3 | null {
  return REFERENCE_KINDS.has(value as WorkbenchReferenceKindV3)
    ? (value as WorkbenchReferenceKindV3)
    : null;
}

function mergedReferenceContext(
  current: WorkbenchContextState,
  reference: WorkbenchReferenceSummaryV3,
): WorkbenchContextState {
  const patch: Partial<Record<WorkbenchContextKey, string>> = {};
  for (const [key, value] of Object.entries(reference.context)) {
    if (value) patch[key as WorkbenchContextKey] = value;
  }
  return patchWorkbenchContext(current, patch);
}

export function referenceHref(
  reference: WorkbenchReferenceSummaryV3,
  current: WorkbenchContextState,
): string {
  return `${reference.detail_url}${workbenchContextSearch(
    mergedReferenceContext(current, reference),
  )}`;
}

export function referenceTargetHref(
  reference: WorkbenchReferenceSummaryV3,
  current: WorkbenchContextState,
): string {
  if (!reference.target_url) return "";
  const [pathname, existingSearch = ""] = reference.target_url.split("?", 2);
  const params = new URLSearchParams(existingSearch);
  const context = mergedReferenceContext(current, reference);
  const contextParams = new URLSearchParams(
    workbenchContextSearch(context).replace(/^\?/, ""),
  );
  for (const [key, value] of contextParams.entries()) params.set(key, value);
  const search = params.toString();
  return `${pathname}${search ? `?${search}` : ""}`;
}

function RelatedReference({
  reference,
  context,
}: {
  reference: WorkbenchReferenceSummaryV3;
  context: WorkbenchContextState;
}) {
  return (
    <Link className="reference-related-card" to={referenceHref(reference, context)}>
      <div>
        <strong>{reference.label}</strong>
        <span className="mono">{reference.identity}</span>
      </div>
      <div className="reference-related-meta">
        <StatusBadge value={reference.kind} tone="neutral" />
        <StatusBadge value={reference.authority} tone="neutral" />
      </div>
    </Link>
  );
}

function ArtifactPreview({ artifactId }: { artifactId: string }) {
  const query = useWorkbenchQuery({
    key: ["artifact-inspection", artifactId],
    queryFn: () => workspaceApi.artifactV3(artifactId),
  });
  if (query.isPending) return <LoadingState label="Loading verified artifact preview" />;
  if (query.error) return <ErrorState error={query.error} />;
  if (!query.data) return null;
  const preview = query.data.preview;
  return (
    <section className="reference-panel">
      <header>
        <FileCode2 size={16} />
        <strong>Artifact Inspector</strong>
        <StatusBadge value={query.data.artifact_type} tone="neutral" />
      </header>
      <div className="reference-boundary-note">
        <LockKeyhole size={14} />
        Browser paths are not accepted. This preview is resolved from the verified Workspace artifact catalog only.
      </div>
      <dl className="reference-grid">
        <div><dt>Verification</dt><dd>{query.data.verification}</dd></div>
        <div><dt>Registered source</dt><dd>{query.data.source.registered ? "yes" : "no"}</dd></div>
        <div><dt>Source URI</dt><dd className="mono">{query.data.source.display_uri || "metadata-only"}</dd></div>
        <div><dt>Evidence</dt><dd>{query.data.evidence_ids.join(", ") || "—"}</dd></div>
      </dl>
      {preview?.kind === "text" ? (
        <pre className="reference-preview">{String(preview.content ?? "")}</pre>
      ) : preview?.kind === "metadata" ? (
        <pre className="reference-preview">{JSON.stringify(preview.content ?? {}, null, 2)}</pre>
      ) : (
        <div className="reference-empty">
          {preview?.reason ?? `Preview kind: ${preview?.kind ?? "none"}`}
        </div>
      )}
      {preview?.truncated ? <div className="reference-truncated">Preview truncated at the server-side safety limit.</div> : null}
    </section>
  );
}

export function WorkbenchReferencePage() {
  const params = useParams();
  const kind = refKind(decodeURIComponent(params.kind ?? ""));
  const identity = decodeURIComponent(params.identity ?? "");
  const { context } = useWorkbenchContext();
  const query = useWorkbenchQuery({
    key: ["workbench-reference", kind ?? "invalid", identity],
    queryFn: () => workspaceApi.referenceV3(kind as WorkbenchReferenceKindV3, identity),
    enabled: Boolean(kind && identity),
  });

  if (!kind || !identity) {
    return <ErrorState error={new Error("Unsupported or empty Workbench reference")} />;
  }
  if (query.isPending) return <LoadingState label="Resolving typed Workbench reference" />;
  if (query.error) return <ErrorState error={query.error} />;
  if (!query.data) return null;

  const reference = query.data;
  const target = referenceTargetHref(reference, context);
  return (
    <div className="reference-page">
      <header className="reference-page-header">
        <div>
          <span className="eyebrow">V3-3 · typed deep link</span>
          <h1>{reference.label}</h1>
          <p className="mono">{reference.identity}</p>
        </div>
        <div className="reference-header-status">
          <StatusBadge value={reference.kind} tone="neutral" />
          <StatusBadge value={reference.authority} tone="neutral" />
          <StatusBadge value={reference.verification} tone="neutral" />
        </div>
      </header>

      <section className="reference-panel">
        <header>
          <Link2 size={16} />
          <strong>Canonical reference</strong>
        </header>
        <dl className="reference-grid">
          <div><dt>Kind</dt><dd>{reference.kind}</dd></div>
          <div><dt>Identity</dt><dd className="mono">{reference.identity}</dd></div>
          <div><dt>Authority</dt><dd>{reference.authority}</dd></div>
          <div><dt>Verification</dt><dd>{reference.verification}</dd></div>
        </dl>
        {Object.keys(reference.context).length ? (
          <div className="reference-context">
            <strong>Context patch</strong>
            {Object.entries(reference.context).map(([key, value]) => (
              <span key={key}><b>{key}</b><code>{value}</code></span>
            ))}
          </div>
        ) : null}
        {target ? (
          <Link className="reference-target" to={target}>
            Open canonical product surface <ExternalLink size={14} />
          </Link>
        ) : null}
      </section>

      {reference.kind === "artifact" ? <ArtifactPreview artifactId={reference.identity} /> : null}

      <section className="reference-panel">
        <header>
          <Network size={16} />
          <strong>Verified related identities</strong>
          <span>{reference.related.length}</span>
        </header>
        {reference.related.length ? (
          <div className="reference-related-list">
            {reference.related.map((item) => (
              <RelatedReference
                key={`${item.kind}:${item.identity}`}
                reference={item}
                context={context}
              />
            ))}
          </div>
        ) : (
          <div className="reference-empty">No additional verified relation is present in the configured Evidence Plane.</div>
        )}
      </section>

      <section className="reference-panel">
        <header><strong>Projection metadata</strong></header>
        <pre className="reference-preview">{JSON.stringify(reference.metadata, null, 2)}</pre>
      </section>

      <div className="reference-boundary-note">
        <LockKeyhole size={14} />
        Unknown or ambiguous identities remain unresolved. Phoenix/OTLP is diagnostic only and hidden reasoning is not a product reference.
      </div>
    </div>
  );
}
