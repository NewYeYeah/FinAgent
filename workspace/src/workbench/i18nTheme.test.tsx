import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { controlApi } from "../api";
import { HIGH_CONTRAST_THEME, WORKBENCH_LOCALE_STORAGE_KEY } from "../i18n";
import { ResearchObjective, ResearchToolCard } from "./research";
import { R4TerminalSummary } from "./researchTerminal";
import { WorkbenchProviders, WorkbenchShell } from "./shell";
import type { ResearchTool } from "./researchTypes";

function LocationProbe() {
  const location = useLocation();
  return <output data-testid="location-probe">{location.pathname}{location.search}</output>;
}

function renderWorkbench(path = "/agent?run=run-123&factor=factor-1&experiment=exp-1") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <WorkbenchProviders>
        <WorkbenchShell>
          <LocationProbe />
          <R4TerminalSummary />
          <ResearchObjective onStarted={vi.fn()} />
          <ResearchToolCard
            status="succeeded"
            tool={{
              tool: "propose_factor",
              arguments: {},
              policy: { outcome: "allow", reason: "typed_fixture" },
              result: { outcome: "VALIDATED", proposal: { factor_id: "factor-new", proposed_at: "2026-09-08T00:00:00Z", proposal_context_id: "ctx-a", history_cutoff: "step-1" } },
            } as unknown as ResearchTool}
          />
        </WorkbenchShell>
      </WorkbenchProviders>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  window.localStorage.clear();
  vi.spyOn(controlApi, "status").mockRejectedValue(new Error("control unavailable"));
  vi.spyOn(controlApi, "commands").mockRejectedValue(new Error("control unavailable"));
  vi.spyOn(controlApi, "researchStatus").mockResolvedValue({ provider_available: false, cancel_supported: false });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
  document.documentElement.lang = "";
});

describe("Workbench bilingual high-contrast UI", () => {
  it("renders English navigation by default and preserves canonical values", async () => {
    renderWorkbench();
    const nav = screen.getByRole("navigation", { name: "FinAgent Workbench modules" });
    for (const label of ["Agent", "Experiments", "Research Graph", "Market", "Factors", "Strategy", "Portfolio", "Execution", "Evidence", "Configuration"]) {
      expect(within(nav).getByText(label)).toBeVisible();
    }
    expect(within(nav).getByRole("link", { name: "Agent" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByTestId("workbench-context-bar")).toHaveTextContent("run-123");
    expect(screen.getByTestId("workbench-context-bar")).toHaveTextContent("factor-1");
    expect(screen.getByText("No adaptive strategy candidate")).toBeVisible();
    expect(screen.getByText("NO_ADAPTIVE_CANDIDATE")).toBeVisible();
    expect(screen.getByText("AgentValue INCONCLUSIVE")).toBeVisible();
    expect(screen.getByText("NONE")).toBeVisible();
    expect(screen.getByText("NOT STARTED")).toBeVisible();
    expect(screen.getByRole("button", { name: "Start bounded research run" })).toBeDisabled();
    expect(screen.getByRole("article", { name: "Factor proposal" })).toBeVisible();
    await waitFor(() => expect(document.documentElement.dataset.theme).toBe(HIGH_CONTRAST_THEME));
    expect(document.documentElement.lang).toBe("en");
  });

  it("toggles to zh-CN without changing route or WorkbenchContext and persists the locale", async () => {
    const user = userEvent.setup();
    renderWorkbench();
    const original = screen.getByTestId("location-probe").textContent;
    await user.click(within(screen.getByTestId("locale-toggle")).getByRole("button", { name: "中文" }));

    const nav = await screen.findByRole("navigation", { name: "FinAgent Workbench 模块" });
    for (const label of ["智能体", "实验", "研究图谱", "市场状态", "因子", "策略", "组合", "执行", "证据", "配置"]) {
      expect(within(nav).getByText(label)).toBeVisible();
    }
    expect(screen.getByTestId("location-probe")).toHaveTextContent(original ?? "");
    expect(screen.getByTestId("workbench-context-bar")).toHaveTextContent("run-123");
    expect(screen.getByTestId("workbench-context-bar")).toHaveTextContent("factor-1");
    expect(screen.getByText("无自适应候选策略")).toBeVisible();
    expect(screen.getByText("NO_ADAPTIVE_CANDIDATE")).toBeVisible();
    expect(screen.getByText("AgentValue INCONCLUSIVE")).toBeVisible();
    expect(screen.getByText("研究目标 / 会话")).toBeVisible();
    expect(screen.getByRole("button", { name: "启动受限研究运行" })).toBeDisabled();
    expect(screen.getByRole("article", { name: "因子提案" })).toBeVisible();
    expect(window.localStorage.getItem(WORKBENCH_LOCALE_STORAGE_KEY)).toBe("zh-CN");
    expect(document.documentElement.lang).toBe("zh-CN");

    cleanup();
    renderWorkbench("/market?market_model=model-a&factor=factor-1");
    expect(await screen.findByRole("navigation", { name: "FinAgent Workbench 模块" })).toBeVisible();
    expect(screen.getByTestId("location-probe")).toHaveTextContent("/market?market_model=model-a&factor=factor-1");
  });
});
