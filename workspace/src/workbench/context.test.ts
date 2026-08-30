import { describe, expect, it } from "vitest";

import {
  parseWorkbenchContext,
  patchWorkbenchContext,
  serializeWorkbenchContext,
  workbenchContextSearch,
} from "./context";

describe("WorkbenchContext URL contract", () => {
  it("round-trips canonical context while preserving unrelated query parameters", () => {
    const current = new URLSearchParams("left=a4-old&right=a4-new&asset=stale");
    const serialized = serializeWorkbenchContext(current, {
      project_id: "project-a",
      thread_id: "thread-a",
      run_id: "run-a",
      portfolio_validation_id: "a4-validation-a",
      asset_id: "600519.SH",
      order_id: "order-a",
      session_date: "2024-06-03",
      date_range: "2024-01-01..2024-12-31",
      fold_id: "wf-1",
    });
    expect(serialized.get("left")).toBe("a4-old");
    expect(serialized.get("right")).toBe("a4-new");
    expect(serialized.get("project")).toBe("project-a");
    expect(serialized.get("thread")).toBe("thread-a");
    expect(serialized.get("run")).toBe("run-a");
    expect(serialized.get("portfolio")).toBe("a4-validation-a");
    expect(serialized.get("asset")).toBe("600519.SH");
    expect(serialized.get("order")).toBe("order-a");
    expect(serialized.get("session")).toBe("2024-06-03");
    expect(serialized.get("fold")).toBe("wf-1");
    expect(parseWorkbenchContext(serialized)).toEqual({
      project_id: "project-a",
      thread_id: "thread-a",
      run_id: "run-a",
      portfolio_validation_id: "a4-validation-a",
      asset_id: "600519.SH",
      order_id: "order-a",
      date_range: "2024-01-01..2024-12-31",
      session_date: "2024-06-03",
      fold_id: "wf-1",
    });
  });

  it("serializes only linked context for cross-module navigation", () => {
    expect(
      workbenchContextSearch({
        project_id: "project-a",
        run_id: "run-a",
        portfolio_validation_id: "a4-validation-a",
        order_id: "order-a",
        environment: "research",
      }),
    ).toBe("?project=project-a&run=run-a&portfolio=a4-validation-a&order=order-a&env=research");
  });

  it("clears dependent identities explicitly instead of mutating unrelated context", () => {
    const next = patchWorkbenchContext(
      {
        project_id: "project-a",
        thread_id: "thread-a",
        run_id: "run-a",
        portfolio_validation_id: "a4-validation-a",
        asset_id: "600519.SH",
        order_id: "order-a",
        environment: "research",
      },
      {
        project_id: "project-b",
        thread_id: null,
        run_id: null,
        asset_id: "000001.SZ",
        order_id: null,
      },
    );
    expect(next).toEqual({
      project_id: "project-b",
      portfolio_validation_id: "a4-validation-a",
      asset_id: "000001.SZ",
      environment: "research",
    });
  });
});
