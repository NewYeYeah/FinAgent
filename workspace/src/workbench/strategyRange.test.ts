import { describe, expect, it } from "vitest";

import { parseWorkbenchContext } from "./context";

describe("Strategy WorkbenchContext range", () => {
  it("preserves the canonical date_range value used by V4.2", () => {
    const context = parseWorkbenchContext(
      new URLSearchParams("portfolio=a4-v42&asset=asset-v42&range=2024-01-02..2024-01-31&fold=wf-2024"),
    );
    expect(context.portfolio_validation_id).toBe("a4-v42");
    expect(context.asset_id).toBe("asset-v42");
    expect(context.date_range).toBe("2024-01-02..2024-01-31");
    expect(context.fold_id).toBe("wf-2024");
  });
});
