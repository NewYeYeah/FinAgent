import { afterEach, describe, expect, it, vi } from "vitest";

import { factorTearSheetApi } from "./factorApi";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("V4-3 Factor Tear Sheet API client", () => {
  it("encodes only bounded semantic row filters", async () => {
    const fetchMock = vi.fn(() =>
      Promise.resolve(
        new Response(
          JSON.stringify({
            schema_version: "finagent.factor-series.query.v1",
            read_only: true,
            authority: "mixed_persisted_metrics",
            series_id: "factor-series-v43",
            program_result_id: "program-result-v43",
            total: 0,
            offset: 7,
            limit: 5000,
            items: [],
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await factorTearSheetApi.rows("factor-series-v43", {
      featureDigest: "factor:v43",
      foldId: "wf-2",
      seriesKind: "ic",
      metric: "rank_ic",
      labelName: "ret_5d",
      quantile: 3,
      start: "2024-01-02",
      end: "2024-02-02",
      limit: 5000,
      offset: 7,
    });

    const request = String(fetchMock.mock.calls[0]?.[0]);
    expect(request).toContain("/api/v4/factor-series/factor-series-v43/rows?");
    expect(request).toContain("feature_digest=factor%3Av43");
    expect(request).toContain("fold_id=wf-2");
    expect(request).toContain("series_kind=ic");
    expect(request).toContain("metric=rank_ic");
    expect(request).toContain("label_name=ret_5d");
    expect(request).toContain("quantile=3");
    expect(request).toContain("start=2024-01-02");
    expect(request).toContain("end=2024-02-02");
    expect(request).toContain("limit=5000");
    expect(request).toContain("offset=7");
    expect(request.toLowerCase()).not.toMatch(/host_path|output_path|shell|python|broker|live/);
  });
});
