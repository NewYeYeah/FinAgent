import { Command, LockKeyhole, ShieldAlert } from "lucide-react";

import { workspaceApi } from "../api";
import { ErrorState, LoadingState, StatusBadge } from "../components";
import { useControlPlane } from "./control";
import { useWorkbenchQuery } from "./query";
import "./configuration.css";

export function CommandCatalogSurface() {
  const control = useControlPlane();
  const commandsQuery = useWorkbenchQuery({
    key: ["command-catalog"],
    queryFn: workspaceApi.commandCatalogV3,
  });

  if (commandsQuery.isPending) {
    return <LoadingState label="Loading Command Catalog" />;
  }
  if (commandsQuery.error) return <ErrorState error={commandsQuery.error} />;
  if (!commandsQuery.data) return null;

  const catalog = commandsQuery.data;
  const liveById = new Map(
    control.catalog?.items.map((item) => [item.command_id, item]) ?? [],
  );

  return (
    <div className="configuration-workbench-page">
      <header className="configuration-page-header">
        <div>
          <span className="eyebrow">V3-2 · governed command metadata</span>
          <h1>Command Catalog</h1>
          <p>
            Evidence metadata remains read-only. Commands execute only through the
            separately started local Control Plane and only when a reviewed
            application-service binding is ready.
          </p>
        </div>
        <StatusBadge value="EVIDENCE READ_ONLY" tone="neutral" />
      </header>

      <div className="command-catalog">
        <div className="command-boundary">
          {control.available ? <Command size={18} /> : <LockKeyhole size={18} />}
          <div>
            <strong>
              {control.available
                ? "Local Control Plane connected — use the Commands palette"
                : "Command metadata only — local Control Plane unavailable"}
            </strong>
            <p>
              The Evidence API exposes no mutation endpoint. The optional Control
              Plane is local-only and resolves exact application_service_ready L0/L1
              identities; it never falls back to shell or Python execution.
            </p>
          </div>
        </div>

        <div className="command-card-grid">
          {catalog.items.map((command) => {
            // V3 Evidence keeps the frozen command vocabulary. A-C1 operational
            // readiness is owned by the separately running Historical Control Plane.
            const live = liveById.get(command.command_id);
            const visible = live ?? command;
            const ready = Boolean(live?.control_execution_enabled);
            return (
              <article className="command-card" key={command.command_id}>
                <header>
                  <StatusBadge value={visible.level} tone="neutral" />
                  <StatusBadge value={visible.gateway_readiness} tone="neutral" />
                </header>
                <h3>{visible.title}</h3>
                <p>{visible.description}</p>
                <dl>
                  <dt>Command ID</dt>
                  <dd className="mono">{visible.command_id}</dd>
                  <dt>Binding</dt>
                  <dd className="mono">{visible.binding_ref}</dd>
                  <dt>Config</dt>
                  <dd>{visible.config_descriptor_ids.join(", ") || "none"}</dd>
                  <dt>Produces</dt>
                  <dd>{visible.produces.join(", ") || "none"}</dd>
                </dl>
                <button
                  type="button"
                  disabled
                  aria-label={`${visible.title} catalog status`}
                >
                  {ready ? (
                    <>
                      <Command size={13} /> Ready in governed Command Palette
                    </>
                  ) : (
                    <>
                      <LockKeyhole size={13} /> Adapter required · not executable
                    </>
                  )}
                </button>
              </article>
            );
          })}
        </div>

        <section className="command-forbidden">
          <ShieldAlert size={17} />
          <div>
            <strong>Generic Control Plane forbidden authority</strong>
            <p>{catalog.forbidden_authority.join(" · ")}</p>
          </div>
        </section>
      </div>
    </div>
  );
}
