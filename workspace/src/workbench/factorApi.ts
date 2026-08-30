import type {
  FactorCorrelationV4,
  FactorHeatmapV4,
  FactorProvenanceV4,
  FactorSeriesCatalogV4,
  FactorSeriesDetailV4,
  FactorSeriesDimensionsV4,
  FactorSeriesItemV4,
  FactorSeriesQueryV4,
  FactorSummaryV4,
} from "./factorTypes";

const API_BASE = (import.meta.env.VITE_API_BASE ?? "").replace(/\/$/, "");

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: "GET",
    headers: { Accept: "application/json" },
  });
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const payload = (await response.json()) as { detail?: string };
      if (payload.detail) detail = payload.detail;
    } catch {
      // Keep the HTTP fallback for non-JSON error bodies.
    }
    throw new Error(detail);
  }
  return (await response.json()) as T;
}

function rowsPath(
  seriesId: string,
  filters: {
    featureDigest?: string;
    foldId?: string;
    seriesKind?: string;
    metric?: string;
    labelName?: string;
    quantile?: number;
    start?: string;
    end?: string;
    limit?: number;
    offset?: number;
  },
): string {
  const params = new URLSearchParams();
  if (filters.featureDigest) params.set("feature_digest", filters.featureDigest);
  if (filters.foldId) params.set("fold_id", filters.foldId);
  if (filters.seriesKind) params.set("series_kind", filters.seriesKind);
  if (filters.metric) params.set("metric", filters.metric);
  if (filters.labelName) params.set("label_name", filters.labelName);
  if (filters.quantile != null) params.set("quantile", String(filters.quantile));
  if (filters.start) params.set("start", filters.start);
  if (filters.end) params.set("end", filters.end);
  params.set("limit", String(filters.limit ?? 1000));
  params.set("offset", String(filters.offset ?? 0));
  return `/api/v4/factor-series/${encodeURIComponent(seriesId)}/rows?${params.toString()}`;
}

export const factorTearSheetApi = {
  catalog: () => getJson<FactorSeriesCatalogV4>("/api/v4/factor-series"),
  byProgram: (programId: string) =>
    getJson<FactorSeriesItemV4>(
      `/api/v4/factor-series/by-program/${encodeURIComponent(programId)}`,
    ),
  detail: (seriesId: string) =>
    getJson<FactorSeriesDetailV4>(`/api/v4/factor-series/${encodeURIComponent(seriesId)}`),
  dimensions: (seriesId: string) =>
    getJson<FactorSeriesDimensionsV4>(
      `/api/v4/factor-series/${encodeURIComponent(seriesId)}/dimensions`,
    ),
  summary: (seriesId: string, featureDigest?: string) => {
    const params = new URLSearchParams();
    if (featureDigest) params.set("feature_digest", featureDigest);
    const suffix = params.size ? `?${params.toString()}` : "";
    return getJson<FactorSummaryV4>(
      `/api/v4/factor-series/${encodeURIComponent(seriesId)}/summary${suffix}`,
    );
  },
  correlations: (seriesId: string) =>
    getJson<FactorCorrelationV4>(
      `/api/v4/factor-series/${encodeURIComponent(seriesId)}/correlations`,
    ),
  heatmap: (
    seriesId: string,
    filters: { featureDigest?: string; labelName?: string; metric?: "rank_ic" | "pearson_ic" },
  ) => {
    const params = new URLSearchParams();
    if (filters.featureDigest) params.set("feature_digest", filters.featureDigest);
    if (filters.labelName) params.set("label_name", filters.labelName);
    if (filters.metric) params.set("metric", filters.metric);
    const suffix = params.size ? `?${params.toString()}` : "";
    return getJson<FactorHeatmapV4>(
      `/api/v4/factor-series/${encodeURIComponent(seriesId)}/heatmap${suffix}`,
    );
  },
  provenance: (seriesId: string) =>
    getJson<FactorProvenanceV4>(
      `/api/v4/factor-series/${encodeURIComponent(seriesId)}/provenance`,
    ),
  rows: (
    seriesId: string,
    filters: {
      featureDigest?: string;
      foldId?: string;
      seriesKind?: string;
      metric?: string;
      labelName?: string;
      quantile?: number;
      start?: string;
      end?: string;
      limit?: number;
      offset?: number;
    },
  ) => getJson<FactorSeriesQueryV4>(rowsPath(seriesId, filters)),
};
