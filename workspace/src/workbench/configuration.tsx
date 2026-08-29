import { useMemo, useState } from "react";
import { GitCompareArrows, KeyRound, LockKeyhole, ShieldAlert } from "lucide-react";

import { workspaceApi } from "../api";
import { ErrorState, LoadingState, StatusBadge } from "../components";
import { useWorkbenchQuery } from "./query";
import type {
  CommandCatalogResponseV3,
  ConfigDescriptorV3,
  ConfigDomainV3,
  ConfigRegistryResponseV3,
  ConfigSnapshotV3,
  JsonValueV3,
} from "./types";
import "./configuration.css";

export type ConfigurationSurface = "configs" | "commands";

const DOMAIN_ORDER: ConfigDomainV3[] = [
  "research_protocol",
  "execution_protocol",
  "operational_guardrail",
  "runtime",
  "secret_reference",
  "presentation",
];

function valueText(value: JsonValueV3 | undefined): string {
  if (value === undefined) return "—";
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}

function ConfigDescriptorList({
  registry,
  selected,
  onSelect,
}: {
  registry: ConfigRegistryResponseV3;
  selected?: string;
  onSelect: (descriptorId: string) => void;
}) {
  return (
    <aside className="config-catalog-index">
      <header>
        <strong>Config Registry</strong>
        <span>{registry.descriptors.length} descriptors</span>
      </header>
      <div className="config-descriptor-list">
        {registry.descriptors.map((descriptor) => (
          <button
            type="button"
            key={descriptor.descriptor_id}
            className={descriptor.descriptor_id === selected ? "selected" : ""}
            onClick={() => onSelect(descriptor.descriptor_id)}
          >
            <strong>{descriptor.title}</strong>
            <span className="mono">{descriptor.descriptor_id}</span>
            <small>{descriptor.fields.length} fields · {descriptor.snapshot_ids.length} snapshots</small>
          </button>
        ))}
      </div>
    </aside>
  );
}

function DomainSummary({ descriptor }: { descriptor: ConfigDescriptorV3 }) {
  const counts = useMemo(() => {
    const result = new Map<ConfigDomainV3, number>();
    for (const field of descriptor.fields) {
      result.set(field.domain, (result.get(field.domain) ?? 0) + 1);
    }
    return result;
  }, [descriptor]);
  return (
    <div className="config-domain-summary">
      {DOMAIN_ORDER.flatMap((domain) => {
        const count = counts.get(domain);
        return count ? [<span key={domain}><b>{domain}</b>{count}</span>] : [];
      })}
    </div>
  );
}

function SnapshotFields({ snapshot }: { snapshot: ConfigSnapshotV3 }) {
  const rows = Object.keys(snapshot.values).sort();
  return (
    <div className="config-field-table" role="table" aria-label="Configuration snapshot fields">
      <div className="config-field-row config-field-head" role="row">
        <span>Field</span><span>Value</span><span>Domain</span><span>Change policy</span>
      </div>
      {rows.map((fieldPath) => (
        <div className="config-field-row" role="row" key={fieldPath}>
          <span className="mono" title={fieldPath}>{fieldPath}</span>
          <span className="config-value" title={valueText(snapshot.values[fieldPath])}>
            {snapshot.redacted_fields.includes(fieldPath) ? <KeyRound size={12} /> : null}
            {valueText(snapshot.values[fieldPath])}
          </span>
          <span><StatusBadge value={snapshot.domains[fieldPath]} tone="neutral" /></span>
          <span className="mono subtle">{snapshot.mutation_policies[fieldPath]}</span>
        </div>
      ))}
    </div>
  );
}

function ConfigCatalog({ registry }: { registry: ConfigRegistryResponseV3 }) {
  const [descriptorId, setDescriptorId] = useState<string | undefined>(registry.descriptors[0]?.descriptor_id);
  const descriptor = registry.descriptors.find((item) => item.descriptor_id === descriptorId) ?? registry.descriptors[0];
  const snapshots = registry.snapshots.filter((item) => item.descriptor_id === descriptor?.descriptor_id);
  const [snapshotChoice, setSnapshotChoice] = useState<string>("");
  const snapshot = snapshots.find((item) => item.snapshot_id === snapshotChoice) ?? snapshots[0];
  const [compareChoice, setCompareChoice] = useState<string>("");
  const compareSnapshot = snapshots.find((item) => item.snapshot_id === compareChoice);
  const diffQuery = useWorkbenchQuery({
    key: ["config-diff", snapshot?.snapshot_id ?? "", compareSnapshot?.snapshot_id ?? ""],
    queryFn: () => workspaceApi.configDiffV3(snapshot?.snapshot_id ?? "", compareSnapshot?.snapshot_id ?? ""),
    enabled: Boolean(snapshot && compareSnapshot && snapshot.snapshot_id !== compareSnapshot.snapshot_id),
  });

  if (!descriptor || !snapshot) {
    return <div className="config-empty">No supported public configuration snapshots were discovered.</div>;
  }

  return (
    <div className="config-catalog-grid">
      <ConfigDescriptorList
        registry={registry}
        selected={descriptor.descriptor_id}
        onSelect={(next) => {
          setDescriptorId(next);
          setSnapshotChoice("");
          setCompareChoice("");
        }}
      />
      <section className="config-catalog-main">
        <header className="config-detail-header">
          <div>
            <span className="eyebrow">ConfigDescriptor</span>
            <h2>{descriptor.title}</h2>
            <p className="mono">[{descriptor.section}] · read-only</p>
          </div>
          <StatusBadge value={descriptor.default_domain} tone="neutral" />
        </header>
        <DomainSummary descriptor={descriptor} />
        <div className="config-snapshot-toolbar">
          <label>
            Snapshot
            <select value={snapshot.snapshot_id} onChange={(event) => { setSnapshotChoice(event.target.value); setCompareChoice(""); }}>
              {snapshots.map((item) => <option key={item.snapshot_id} value={item.snapshot_id}>{item.source_uri}</option>)}
            </select>
          </label>
          {snapshots.length > 1 ? (
            <label>
              Compare with
              <select value={compareChoice} onChange={(event) => setCompareChoice(event.target.value)}>
                <option value="">No comparison</option>
                {snapshots.filter((item) => item.snapshot_id !== snapshot.snapshot_id).map((item) => (
                  <option key={item.snapshot_id} value={item.snapshot_id}>{item.source_uri}</option>
                ))}
              </select>
            </label>
          ) : null}
        </div>
        <div className="config-snapshot-identity">
          <span className="mono">{snapshot.snapshot_id}</span>
          <span className="mono subtle">sha256:{snapshot.source_sha256.slice(0, 16)}…</span>
          {snapshot.redacted_fields.length ? <span><KeyRound size={12} /> {snapshot.redacted_fields.length} protected reference(s)</span> : null}
        </div>
        <SnapshotFields snapshot={snapshot} />
        {compareSnapshot ? (
          <section className="config-diff-panel">
            <header><GitCompareArrows size={16} /><strong>ConfigDiff</strong></header>
            {diffQuery.isPending ? <LoadingState label="Comparing snapshots" /> : null}
            {diffQuery.error ? <ErrorState error={diffQuery.error} /> : null}
            {diffQuery.data ? (
              <>
                <div className={`config-diff-verdict ${diffQuery.data.requires_new_identity ? "identity-change" : "runtime-change"}`}>
                  {diffQuery.data.requires_new_identity
                    ? "Protocol/guardrail change detected — a new governed identity is required."
                    : "Only runtime/presentation/reference changes detected by this comparison."}
                </div>
                <div className="config-diff-list">
                  {diffQuery.data.changes.map((item) => (
                    <div key={item.field_path}>
                      <strong className="mono">{item.field_path}</strong>
                      <span>{valueText(item.before)} → {valueText(item.after)}</span>
                      <span>{item.domain} · {item.mutation_policy}</span>
                    </div>
                  ))}
                  {!diffQuery.data.changes.length ? <p>No semantic field changes.</p> : null}
                </div>
              </>
            ) : null}
          </section>
        ) : null}
      </section>
    </div>
  );
}

function CommandCatalog({ catalog }: { catalog: CommandCatalogResponseV3 }) {
  return (
    <div className="command-catalog">
      <div className="command-boundary">
        <LockKeyhole size={18} />
        <div>
          <strong>Catalog only — Control Plane disabled</strong>
          <p>V3-2B freezes typed command metadata. No command execution endpoint exists in this phase.</p>
        </div>
      </div>
      <div className="command-card-grid">
        {catalog.items.map((command) => (
          <article className="command-card" key={command.command_id}>
            <header>
              <StatusBadge value={command.level} tone="neutral" />
              <StatusBadge value={command.gateway_readiness} tone="neutral" />
            </header>
            <h3>{command.title}</h3>
            <p>{command.description}</p>
            <dl>
              <dt>Command ID</dt><dd className="mono">{command.command_id}</dd>
              <dt>Binding</dt><dd className="mono">{command.binding_ref}</dd>
              <dt>Config</dt><dd>{command.config_descriptor_ids.join(", ") || "none"}</dd>
              <dt>Produces</dt><dd>{command.produces.join(", ") || "none"}</dd>
            </dl>
            <button type="button" disabled aria-label={`${command.title} execution disabled`}>
              <LockKeyhole size={13} /> Execution disabled · V3-2C
            </button>
          </article>
        ))}
      </div>
      <section className="command-forbidden">
        <ShieldAlert size={17} />
        <div>
          <strong>Generic gateway forbidden authority</strong>
          <p>{catalog.forbidden_authority.join(" · ")}</p>
        </div>
      </section>
    </div>
  );
}

export function ConfigurationCatalogSurface({ surface }: { surface: ConfigurationSurface }) {
  const registryQuery = useWorkbenchQuery({
    key: ["config-registry"],
    queryFn: workspaceApi.configRegistryV3,
    enabled: surface === "configs",
  });
  const commandsQuery = useWorkbenchQuery({
    key: ["command-catalog"],
    queryFn: workspaceApi.commandCatalogV3,
    enabled: surface === "commands",
  });

  const loading = surface === "configs" ? registryQuery.isPending : commandsQuery.isPending;
  const error = surface === "configs" ? registryQuery.error : commandsQuery.error;
  if (loading) return <LoadingState label={surface === "configs" ? "Loading Config Registry" : "Loading Command Catalog"} />;
  if (error) return <ErrorState error={error} />;

  return (
    <div className="configuration-workbench-page">
      <header className="configuration-page-header">
        <div>
          <span className="eyebrow">V3-2B · product contract</span>
          <h1>{surface === "configs" ? "Configuration Registry" : "Command Catalog"}</h1>
          <p>{surface === "configs"
            ? "Public, redacted configuration snapshots with explicit authority domains and identity-change semantics."
            : "Allowlisted future L0/L1 commands. Metadata is inspectable now; execution remains disabled until V3-2C."}</p>
        </div>
        <StatusBadge value="READ_ONLY" tone="neutral" />
      </header>
      {surface === "configs" && registryQuery.data ? (
        <>
          {registryQuery.data.warnings.length ? (
            <div className="config-warning-box">{registryQuery.data.warnings.join(" · ")}</div>
          ) : null}
          <ConfigCatalog registry={registryQuery.data} />
        </>
      ) : null}
      {surface === "commands" && commandsQuery.data ? <CommandCatalog catalog={commandsQuery.data} /> : null}
    </div>
  );
}
