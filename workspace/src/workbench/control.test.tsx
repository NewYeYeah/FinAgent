import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import { CommandPalette } from "./control";
import { WorkbenchProviders } from "./shell";

function response(payload: unknown, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(payload), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

const controlStatus = {
  schema_version: "finagent.workbench.control-status.v1",
  version: "finagent-workbench-control-api-v3.2",
  control_plane_enabled: true,
  local_only: true,
  remote_binding_supported: false,
  requested_by: "tester",
  application_service_ready: [
    "config.validate",
    "data.certify_local_ashare",
    "review.export_bundle",
  ],
  recovered_incomplete_runs: [],
  store: {
    schema_version: "finagent.workbench.command-store.v1",
    run_counts: {},
    terminal_states: ["failed", "rejected", "succeeded"],
  },
  forbidden_authority: [
    "production_reserve",
    "broker_order",
    "arbitrary_shell",
  ],
};

const command = (
  command_id: string,
  overrides: Record<string, unknown> = {},
) => ({
  schema_version: "finagent.workbench.command-spec.v1",
  command_id,
  title: command_id,
  description: `${command_id} description`,
  level: "L0",
  config_descriptor_ids: [],
  binding_kind: "application_service",
  binding_ref: `finagent.application.${command_id}`,
  gateway_readiness: "application_service_ready",
  produces: [],
  requires_confirmation: false,
  execution_enabled: false,
  catalog_only: true,
  control_execution_enabled: true,
  control_plane_enabled: true,
  ...overrides,
});

const controlCommands = {
  schema_version: "finagent.workbench.control-command-catalog.v1",
  control_plane_enabled: true,
  local_only: true,
  items: [
    command("config.validate", {
      title: "Validate configuration",
      config_descriptor_ids: ["local_ashare"],
    }),
    command("review.export_bundle", { title: "Export review bundle" }),
    command("research.run_a2p6", {
      title: "Run A2.6 robust research",
      level: "L1",
      binding_kind: "cli_orchestration",
      binding_ref: "scripts/run_local_ashare_robust_research.py",
      gateway_readiness: "adapter_required",
      requires_confirmation: true,
      control_execution_enabled: false,
    }),
  ],
  forbidden_authority: controlStatus.forbidden_authority,
};

const configRegistry = {
  schema_version: "finagent.workbench.config-registry.v1",
  read_only: true,
  descriptors: [
    {
      schema_version: "finagent.workbench.config-descriptor.v1",
      descriptor_id: "local_ashare",
      title: "Local A-share certification",
      section: "local_ashare",
      default_domain: "runtime",
      fields: [],
      snapshot_ids: ["config-snapshot-1"],
      read_only: true,
    },
  ],
  snapshots: [
    {
      schema_version: "finagent.workbench.config-snapshot.v1",
      snapshot_id: "config-snapshot-1",
      descriptor_id: "local_ashare",
      section: "local_ashare",
      source_uri: "config://root-0/local.toml",
      source_sha256: "abc",
      values: { root: "D:/Data/A-Share" },
      domains: { root: "runtime" },
      mutation_policies: { root: "restart_or_new_run" },
      redacted_fields: [],
      read_only: true,
    },
  ],
  warnings: [],
};

const succeededRun = {
  schema_version: "finagent.workbench.command-record.v1",
  intent: {
    schema_version: "finagent.workbench.command-intent.v1",
    intent_id: "command-intent-1",
    command_id: "review.export_bundle",
    config_snapshot_id: null,
    context: { portfolio_validation_id: "a4-validation-1" },
    requested_by: "tester",
    state: "validated",
  },
  run: {
    schema_version: "finagent.workbench.command-run.v1",
    command_run_id: "command-run-1",
    intent_id: "command-intent-1",
    command_id: "review.export_bundle",
    state: "succeeded",
    started_at: "2026-08-29T12:00:00+00:00",
    finished_at: "2026-08-29T12:00:01+00:00",
  },
  parameters: { validation_id: "a4-validation-1" },
  created_at: "2026-08-29T12:00:00+00:00",
  updated_at: "2026-08-29T12:00:01+00:00",
  result: {
    schema_version: "finagent.workbench.command-result.v1",
    command_run_id: "command-run-1",
    status: "succeeded",
    evidence_ids: ["a4-validation-1"],
    message: "human-review bundle exported",
  },
  artifact_paths: [
    ".finagent/workbench/exports/finagent-review-a4-validation-1.zip",
  ],
  outputs: {},
  events: [
    {
      schema_version: "finagent.workbench.command-event.v1",
      event_id: "event-1",
      command_run_id: "command-run-1",
      sequence: 1,
      event_type: "RUN_PLANNED",
      state: "planned",
      occurred_at: "2026-08-29T12:00:00+00:00",
      message: "command accepted for execution",
    },
    {
      schema_version: "finagent.workbench.command-event.v1",
      event_id: "event-2",
      command_run_id: "command-run-1",
      sequence: 2,
      event_type: "RUN_STARTED",
      state: "running",
      occurred_at: "2026-08-29T12:00:00+00:00",
      message: "application service execution started",
    },
    {
      schema_version: "finagent.workbench.command-event.v1",
      event_id: "event-3",
      command_run_id: "command-run-1",
      sequence: 3,
      event_type: "RUN_SUCCEEDED",
      state: "succeeded",
      occurred_at: "2026-08-29T12:00:01+00:00",
      message: "human-review bundle exported",
    },
  ],
};

describe("V3-2 Command Palette", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/api/v3/control/status")) return response(controlStatus);
      if (url.endsWith("/api/v3/control/commands")) {
        return response(controlCommands);
      }
      if (url.endsWith("/api/v3/config")) return response(configRegistry);
      if (url.includes("/api/v3/control/runs?limit=20")) {
        return response({ schema_version: "list", items: [] });
      }
      if (url.endsWith("/api/v3/control/runs") && init?.method === "POST") {
        return response(succeededRun, 200);
      }
      throw new Error(`unexpected URL: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  function renderPalette() {
    render(
      <MemoryRouter initialEntries={["/?portfolio=a4-validation-1"]}>
        <WorkbenchProviders>
          <CommandPalette open onClose={() => undefined} />
        </WorkbenchProviders>
      </MemoryRouter>,
    );
  }

  it("shows adapter-required research commands but keeps them non-executable", async () => {
    renderPalette();
    expect(
      await screen.findByText("Local Control Plane connected"),
    ).toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("button", { name: /Run A2.6 robust research/i }),
    );
    expect(
      screen.getByText(/reviewed application-service adapter is not ready/i),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Create governed CommandRun/i }),
    ).toBeDisabled();
  });

  it("creates a governed review-bundle run from WorkbenchContext only", async () => {
    renderPalette();
    await screen.findByText("Local Control Plane connected");
    await userEvent.click(
      screen.getByRole("button", { name: /Export review bundle/i }),
    );
    expect(screen.getByText("a4-validation-1")).toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("button", { name: /Create governed CommandRun/i }),
    );
    expect(await screen.findByText("RUN_SUCCEEDED")).toBeInTheDocument();
    expect(
      screen.getAllByText("human-review bundle exported").length,
    ).toBeGreaterThanOrEqual(1);

    const postCall = fetchMock.mock.calls.find(
      ([input, init]) =>
        String(input).endsWith("/api/v3/control/runs") && init?.method === "POST",
    );
    expect(postCall).toBeTruthy();
    const body = JSON.parse(String(postCall?.[1]?.body));
    expect(body.command_id).toBe("review.export_bundle");
    expect(body.validation_id).toBe("a4-validation-1");
    expect(body.context.portfolio_validation_id).toBe("a4-validation-1");
    expect(body).not.toHaveProperty("shell");
    expect(body).not.toHaveProperty("output");
    expect(body).not.toHaveProperty("reports");
  });
});
