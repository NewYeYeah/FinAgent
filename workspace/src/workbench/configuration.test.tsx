import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("echarts-for-react", () => ({ default: () => <div data-testid="echarts" /> }));
vi.mock("@xyflow/react", () => ({
  ReactFlow: ({ children }: { children?: React.ReactNode }) => (
    <div data-testid="react-flow">{children}</div>
  ),
  Background: () => null,
  Controls: () => null,
  MarkerType: { ArrowClosed: "arrowclosed" },
}));

import App from "../App";

function response(payload: unknown) {
  return Promise.resolve(
    new Response(JSON.stringify(payload), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

const leftId = "config-snapshot-left";
const rightId = "config-snapshot-right";
const registry = {
  schema_version: "finagent.workbench.config-registry.v1",
  read_only: true,
  warnings: [
    "secret-like config excluded without parsing: config-root-0/secrets.toml",
  ],
  descriptors: [
    {
      schema_version: "finagent.workbench.config-descriptor.v1",
      descriptor_id: "local_ashare_robust_research",
      title: "A2.6 robust A-share research",
      section: "local_ashare_robust_research",
      default_domain: "research_protocol",
      snapshot_ids: [leftId, rightId],
      read_only: true,
      fields: [
        {
          field_path: "root",
          label: "root",
          value_type: "string",
          domain: "runtime",
          mutation_policy: "restart_or_new_run",
          required: true,
          secret_redacted: false,
          description: "",
        },
        {
          field_path: "universe_top_n",
          label: "universe top n",
          value_type: "integer",
          domain: "research_protocol",
          mutation_policy: "new_identity_required",
          required: true,
          secret_redacted: false,
          description: "",
        },
        {
          field_path: "secrets_file",
          label: "secrets file",
          value_type: "string",
          domain: "secret_reference",
          mutation_policy: "host_secret_binding_only",
          required: true,
          secret_redacted: true,
          description: "",
        },
      ],
    },
  ],
  snapshots: [
    {
      schema_version: "finagent.workbench.config-snapshot.v1",
      snapshot_id: leftId,
      descriptor_id: "local_ashare_robust_research",
      section: "local_ashare_robust_research",
      source_uri: "config://root-0/left.toml",
      source_sha256: "a".repeat(64),
      values: {
        root: "D:/Data/A-Share",
        universe_top_n: 150,
        secrets_file: "<secret-file-reference>",
      },
      domains: {
        root: "runtime",
        universe_top_n: "research_protocol",
        secrets_file: "secret_reference",
      },
      mutation_policies: {
        root: "restart_or_new_run",
        universe_top_n: "new_identity_required",
        secrets_file: "host_secret_binding_only",
      },
      redacted_fields: ["secrets_file"],
      read_only: true,
    },
    {
      schema_version: "finagent.workbench.config-snapshot.v1",
      snapshot_id: rightId,
      descriptor_id: "local_ashare_robust_research",
      section: "local_ashare_robust_research",
      source_uri: "config://root-0/right.toml",
      source_sha256: "b".repeat(64),
      values: {
        root: "E:/Data/A-Share",
        universe_top_n: 180,
        secrets_file: "<secret-file-reference>",
      },
      domains: {
        root: "runtime",
        universe_top_n: "research_protocol",
        secrets_file: "secret_reference",
      },
      mutation_policies: {
        root: "restart_or_new_run",
        universe_top_n: "new_identity_required",
        secrets_file: "host_secret_binding_only",
      },
      redacted_fields: ["secrets_file"],
      read_only: true,
    },
  ],
};

const diff = {
  schema_version: "finagent.workbench.config-diff.v1",
  diff_id: "config-diff-a",
  descriptor_id: "local_ashare_robust_research",
  left_snapshot_id: leftId,
  right_snapshot_id: rightId,
  requires_new_identity: true,
  read_only: true,
  changes: [
    {
      field_path: "root",
      before: "D:/Data/A-Share",
      after: "E:/Data/A-Share",
      domain: "runtime",
      mutation_policy: "restart_or_new_run",
      requires_new_identity: false,
    },
    {
      field_path: "universe_top_n",
      before: 150,
      after: 180,
      domain: "research_protocol",
      mutation_policy: "new_identity_required",
      requires_new_identity: true,
    },
  ],
};

const commands = {
  schema_version: "finagent.workbench.command-catalog.v1",
  read_only: true,
  execution_enabled: false,
  control_plane_enabled: false,
  forbidden_authority: ["production_reserve", "broker_order", "live_capital"],
  items: [
    {
      schema_version: "finagent.workbench.command-spec.v1",
      command_id: "research.run_a2p6",
      title: "Run A2.6 robust research",
      description:
        "Future governed L1 entry for preregistered robust ResearchProgram execution.",
      level: "L1",
      config_descriptor_ids: ["local_ashare_robust_research"],
      binding_kind: "cli_orchestration",
      binding_ref: "scripts/run_local_ashare_robust_research.py",
      gateway_readiness: "adapter_required",
      produces: ["AshareRobustResearchProgramResult"],
      requires_confirmation: true,
      execution_enabled: false,
      catalog_only: true,
    },
  ],
};

describe("V3-2 Configuration and Command catalogs", () => {
  beforeEach(() => {
    window.history.pushState({}, "", "/widgets?surface=configs&program=program-a");
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith("/api/v3/config")) return response(registry);
        if (url.includes("/api/v3/config/diff?")) return response(diff);
        if (url.endsWith("/api/v3/commands")) return response(commands);
        // The optional Control Plane is deliberately absent in this test. The
        // provider catches the network failure and must not create a fallback path.
        if (url.includes("127.0.0.1:8766/api/v3/control/")) {
          return Promise.reject(new TypeError("control unavailable"));
        }
        throw new Error(`unexpected URL: ${url}`);
      }),
    );
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("renders read-only config domains, protected references and identity semantics", async () => {
    render(<App />);
    expect(await screen.findByText("Configuration Registry")).toBeInTheDocument();
    expect(
      screen.getAllByText("A2.6 robust A-share research").length,
    ).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText("new_identity_required").length).toBeGreaterThan(0);
    expect(screen.getByText("<secret-file-reference>")).toBeInTheDocument();
    expect(
      screen.getByText(/secret-like config excluded without parsing/i),
    ).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.getByTestId("workbench-context-bar")).toHaveTextContent("program-a");

    const compare = screen.getByLabelText("Compare with");
    await userEvent.selectOptions(compare, rightId);
    expect(
      await screen.findByText(/new governed identity is required/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/150 → 180/)).toBeInTheDocument();
  });

  it("navigates to the command catalog without enabling adapter-required execution", async () => {
    render(<App />);
    await screen.findByText("Configuration Registry");
    const commandLink = screen.getByRole("link", { name: "Command Catalog" });
    expect(commandLink).toHaveAttribute(
      "href",
      "/widgets?program=program-a&surface=commands",
    );
    await userEvent.click(commandLink);
    await waitFor(() => expect(window.location.search).toContain("surface=commands"));
    expect(await screen.findByText("Run A2.6 robust research")).toBeInTheDocument();
    expect(screen.getByText("adapter_required")).toBeInTheDocument();
    expect(screen.getByText(/Control Plane unavailable/i)).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: /Run A2.6 robust research catalog status/i,
      }),
    ).toBeDisabled();
    expect(screen.getByText(/Adapter required · not executable/i)).toBeInTheDocument();
    expect(screen.getByText(/production_reserve/)).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /promote|reserve|broker|order/i }),
    ).not.toBeInTheDocument();
  });
});
