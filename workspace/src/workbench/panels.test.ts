import { describe, expect, it } from "vitest";

import { PanelRegistry, defaultPanelRegistry } from "./panels";

describe("PanelRegistry", () => {
  it("exposes current modules and reserved future extension surfaces", () => {
    expect(defaultPanelRegistry.get("agent")).toMatchObject({
      status: "available",
      route: "/agent",
      slot: "main",
    });
    expect(defaultPanelRegistry.get("strategy")).toMatchObject({
      status: "reserved",
      slot: "chart",
    });
    expect(defaultPanelRegistry.get("configuration")).toMatchObject({
      status: "reserved",
      slot: "config",
    });
  });

  it("rejects duplicate panel identity", () => {
    const registry = new PanelRegistry();
    registry.register({
      panel_id: "factor-chart",
      module: "factors",
      title: "Factor chart",
      status: "reserved",
      context_keys: ["factor_id", "date_range"],
      slot: "chart",
    });
    expect(() =>
      registry.register({
        panel_id: "factor-chart",
        module: "factors",
        title: "Duplicate",
        status: "reserved",
        context_keys: [],
        slot: "chart",
      }),
    ).toThrow(/already registered/);
  });
});
