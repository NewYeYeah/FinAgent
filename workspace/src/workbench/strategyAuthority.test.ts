import { describe, expect, it } from "vitest";

import type { StrategySeriesDetailV4 } from "./strategyTypes";

describe("V4 Strategy authority contract", () => {
  it("keeps price and recomputation semantics explicit", () => {
    const presentation: StrategySeriesDetailV4["presentation"] = {
      price_semantics: "authoritative_close_only",
      ohlc_available: false,
      browser_recomputation: false,
      factor_contribution_semantics: "combined alpha context and frozen component identities only",
    };
    expect(presentation.ohlc_available).toBe(false);
    expect(presentation.browser_recomputation).toBe(false);
    expect(presentation.price_semantics).toBe("authoritative_close_only");
  });
});
