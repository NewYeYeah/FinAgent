import { afterEach, describe, expect, it, vi } from "vitest";

import { workspaceApi } from "../api";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("V4 strategy API client", () => {
  it("encodes bounded decision filters without host paths or executable inputs", async () => {
    const fetchMock = vi.fn(() =>
      Promise.resolve(
        new Response(
          JSON.stringify({
            schema_version: "finagent.strategy-decision-series.query.v1",
            read_only: true,
            authority: "authoritative",
            series_id: "series-v42",
            portfolio_validation_id: "a4-v42",
            filters: {},
            total: 0,
            items: [],
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await workspaceApi.strategyDecisionsV4("series-v42", {
      asset: "equity:SSE:600000:CNY",
      start: "2024-01-02",
      end: "2024-01-31",
      foldId: "wf-2024",
      limit: 5000,
      offset: 7,
    });

    const request = String(fetchMock.mock.calls[0]?.[0]);
    expect(request).toContain("/api/v4/strategy-series/series-v42/decisions?");
    expect(request).toContain("asset=equity%3ASSE%3A600000%3ACNY");
    expect(request).toContain("start=2024-01-02");
    expect(request).toContain("end=2024-01-31");
    expect(request).toContain("fold_id=wf-2024");
    expect(request).toContain("limit=5000");
    expect(request).toContain("offset=7");
    expect(request.toLowerCase()).not.toMatch(/shell|python|host_path|output_path/);
  });
});
