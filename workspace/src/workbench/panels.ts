import type { WorkbenchContextKey } from "./context";

export type WorkbenchModule =
  | "command-center"
  | "agent"
  | "strategy"
  | "factors"
  | "portfolio"
  | "execution"
  | "risk"
  | "operations"
  | "evidence"
  | "governance"
  | "configuration"
  | "live";

export type WorkbenchPanelStatus = "available" | "reserved";

export interface WorkbenchPanelDescriptor {
  panel_id: string;
  module: WorkbenchModule;
  title: string;
  route?: string;
  status: WorkbenchPanelStatus;
  context_keys: WorkbenchContextKey[];
  slot: "main" | "chart" | "inspector" | "config" | "command";
}

export class PanelRegistry {
  private readonly panels = new Map<string, WorkbenchPanelDescriptor>();

  constructor(initial: WorkbenchPanelDescriptor[] = []) {
    for (const panel of initial) this.register(panel);
  }

  register(panel: WorkbenchPanelDescriptor) {
    if (this.panels.has(panel.panel_id)) {
      throw new Error(`Workbench panel ${panel.panel_id} is already registered`);
    }
    this.panels.set(panel.panel_id, {
      ...panel,
      context_keys: [...panel.context_keys],
    });
  }

  get(panelId: string): WorkbenchPanelDescriptor | undefined {
    return this.panels.get(panelId);
  }

  list(): WorkbenchPanelDescriptor[] {
    return [...this.panels.values()];
  }
}

export const defaultPanelRegistry = new PanelRegistry([
  { panel_id: "command-center", module: "command-center", title: "Command Center", route: "/", status: "available", context_keys: ["program_id", "portfolio_validation_id", "reserve_id"], slot: "main" },
  { panel_id: "agent", module: "agent", title: "Agent", route: "/agent", status: "available", context_keys: ["project_id", "thread_id", "run_id"], slot: "main" },
  { panel_id: "strategy", module: "strategy", title: "Strategy", status: "reserved", context_keys: ["strategy_id", "asset_id", "date_range"], slot: "chart" },
  { panel_id: "factors", module: "factors", title: "Factors", route: "/research", status: "available", context_keys: ["program_id", "factor_id", "fold_id"], slot: "chart" },
  { panel_id: "portfolio", module: "portfolio", title: "Portfolio", route: "/portfolio", status: "available", context_keys: ["portfolio_validation_id", "date_range", "fold_id"], slot: "chart" },
  { panel_id: "execution", module: "execution", title: "Execution", status: "reserved", context_keys: ["portfolio_validation_id", "asset_id", "session_date"], slot: "chart" },
  { panel_id: "risk", module: "risk", title: "Risk", status: "reserved", context_keys: ["strategy_id", "portfolio_validation_id", "date_range"], slot: "chart" },
  { panel_id: "operations", module: "operations", title: "Operations", status: "reserved", context_keys: ["strategy_id", "environment", "session_date"], slot: "main" },
  { panel_id: "evidence", module: "evidence", title: "Evidence", route: "/catalog", status: "available", context_keys: ["program_id", "factor_id", "portfolio_validation_id", "reserve_id"], slot: "main" },
  { panel_id: "governance", module: "governance", title: "Governance", route: "/governance", status: "available", context_keys: ["program_id", "portfolio_validation_id", "reserve_id"], slot: "main" },
  { panel_id: "reserve", module: "governance", title: "Reserve", route: "/reserve", status: "available", context_keys: ["reserve_id", "program_id", "portfolio_validation_id"], slot: "main" },
  { panel_id: "configuration", module: "configuration", title: "Configuration", status: "reserved", context_keys: ["program_id", "strategy_id", "environment"], slot: "config" },
  { panel_id: "live", module: "live", title: "Live", status: "reserved", context_keys: ["strategy_id", "asset_id", "environment"], slot: "chart" },
]);
