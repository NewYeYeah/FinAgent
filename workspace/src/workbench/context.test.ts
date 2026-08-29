import { describe, expect, it } from "vitest";

import {
  parseWorkbenchContext,
  patchWorkbenchContext,
  serializeWorkbenchContext,
} from "./context";

describe("WorkbenchContext URL contract", () => {
  it("round-trips canonical context while preserving unrelated query parameters", () => {
    const current = new URLSearchParams("left=a4-old&right=a4-new&asset=stale");
    const serialized = serializeWorkbenchContext(current, {
      project_id: "project-a",
      thread_id: "thread-a",
      run_id: "run-a",
      asset_id: "600519.SH",
      date_range: "2024-01-01..2024-12-31",
    });
    expect(serialized.get("left")).toBe("a4-old");
    expect(serialized.get("right")).toBe("a4-new");
    expect(serialized.get("project")).toBe("project-a");
    expect(serialized.get("thread")).toBe("thread-a");
    expect(serialized.get("run")).toBe("run-a");
    expect(serialized.get("asset")).toBe("600519.SH");
    expect(parseWorkbenchContext(serialized)).toEqual({
      project_id: "project-a",
      thread_id: "thread-a",
      run_id: "run-a",
      asset_id: "600519.SH",
      date_range: "2024-01-01..2024-12-31",
    });
  });

  it("clears dependent identities explicitly instead of mutating unrelated context", () => {
    const next = patchWorkbenchContext(
      {
        project_id: "project-a",
        thread_id: "thread-a",
        run_id: "run-a",
        environment: "research",
      },
      { project_id: "project-b", thread_id: null, run_id: null },
    );
    expect(next).toEqual({ project_id: "project-b", environment: "research" });
  });
});
