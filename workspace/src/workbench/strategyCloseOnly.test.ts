import { describe, expect, it } from "vitest";

import type { StrategySeriesDimensionsV4 } from "./strategyTypes";

describe("V4.2 close-only market-price boundary", () => {
  it("does not claim OHLC when V4-0 does not persist it", () => {
    const dimensions = {
      ohlc_available: false,
      price_semantics: "close_price from authoritative A4 close marks",
    } satisfies Pick<StrategySeriesDimensionsV4, "ohlc_available" | "price_semantics">;
    expect(dimensions.ohlc_available).toBe(false);
    expect(dimensions.price_semantics).toMatch(/close_price/);
  });
});
