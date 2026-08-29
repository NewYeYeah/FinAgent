import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("echarts-for-react", () => ({ default: () => <div data-testid="echarts" /> }));
vi.mock("@xyflow/react", () => ({
  ReactFlow: ({ children }: { children?: React.ReactNode }) => <div data-testid="react-flow">{children}</div>,
  Background: () => null,
  Controls: () => null,
  MarkerType: { ArrowClosed: "arrowclosed" },
}));

import App from "../App";

function json(payload: unknown, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(payload), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

const factorReference = {
  schema_version: "finagent.workbench.reference.v1",
  read_only: true,
  kind: "factor",
  identity: "factor-digest",
  label: "momentum-20",
  authority: "authoritative",
  verification: "workspace_projection",
  detail_url: "/ref/factor/factor-digest",
  target_url: "/factor/factor-digest",
  context: { program_id: "program-a26", factor_id: "factor-digest" },
  metadata: { occurrence_count: 1 },
  related: [
    {
      kind: "research_program",
      identity: "program-a26",
      label: "ResearchProgram",
      authority: "authoritative",
      verification: "workspace_projection",
      detail_url: "/ref/research_program/program-a26",
      target_url: "/program/program-a26",
      context: { program_id: "program-a26" },
    },
    {
      kind: "artifact",
      identity: "factor-digest",
      label: "Generated feature artifact",
      authority: "authoritative",
      verification: "workspace_projection",
      detail_url: "/ref/artifact/factor-digest",
      target_url: "/factor/factor-digest",
      context: { factor_id: "factor-digest" },
    },
  ],
};

const artifactReference = {
  schema_version: "finagent.workbench.reference.v1",
  read_only: true,
  kind: "artifact",
  identity: "factor-digest",
  label: "Generated feature · momentum-20",
  authority: "authoritative",
  verification: "workspace_catalog",
  detail_url: "/ref/artifact/factor-digest",
  target_url: "/factor/factor-digest",
  context: {},
  metadata: { artifact_type: "generated_feature" },
  related: [],
};

const artifactInspection = {
  schema_version: "finagent.workbench.artifact-inspection.v1",
  read_only: true,
  artifact_id: "factor-digest",
  artifact_type: "generated_feature",
  label: "Generated feature · momentum-20",
  authority: "authoritative",
  verification: "workspace_catalog",
  evidence_ids: ["evidence-a26"],
  target_url: "/factor/factor-digest",
  metadata: { feature_id: "momentum-20", hypothesis: "continuation" },
  source: {
    registered: false,
    display_uri: "",
    host_path_accepted_from_browser: false,
  },
  preview: {
    kind: "metadata",
    content: { feature_id: "momentum-20", hypothesis: "continuation" },
    truncated: false,
  },
};

describe("V3-3 typed reference inspector", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("127.0.0.1:8766/api/v3/control/")) {
          return Promise.reject(new TypeError("control unavailable"));
        }
        if (url.endsWith("/api/v3/refs/factor/factor-digest")) return json(factorReference);
        if (url.endsWith("/api/v3/refs/artifact/factor-digest")) return json(artifactReference);
        if (url.endsWith("/api/v3/artifacts/factor-digest")) return json(artifactInspection);
        throw new Error(`unexpected URL: ${url}`);
      }),
    );
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("preserves existing WorkbenchContext while applying canonical related context", async () => {
    window.history.pushState({}, "", "/ref/factor/factor-digest?project=project-a&run=run-a");
    render(<App />);
    expect(await screen.findByText("momentum-20")).toBeInTheDocument();
    expect(screen.getByText("Canonical reference")).toBeInTheDocument();
    const program = screen.getByRole("link", { name: /ResearchProgram/i });
    expect(program.getAttribute("href")).toContain("/ref/research_program/program-a26?");
    expect(program.getAttribute("href")).toContain("project=project-a");
    expect(program.getAttribute("href")).toContain("run=run-a");
    expect(program.getAttribute("href")).toContain("program=program-a26");
    expect(screen.getByText(/Phoenix\/OTLP is diagnostic only/i)).toBeInTheDocument();
  });

  it("renders generated-feature metadata without accepting a browser host path", async () => {
    window.history.pushState({}, "", "/ref/artifact/factor-digest");
    render(<App />);
    expect(await screen.findByText("Artifact Inspector")).toBeInTheDocument();
    expect(screen.getByText(/Browser paths are not accepted/i)).toBeInTheDocument();
    expect(screen.getByText(/continuation/i)).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });
});
