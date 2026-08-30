import type {
  PortfolioExecutionAnalyticsV4,
  PortfolioExecutionCatalogV4,
  PortfolioExecutionDetailV4,
  PortfolioSeriesV4,
  StrategyDecisionQueryV4,
} from "./portfolioExecutionTypes";

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
      // Preserve the HTTP fallback for non-JSON bodies.
    }
    throw new Error(detail);
  }
  return (await response.json()) as T;
}

function addCommonFilters(
  params: URLSearchParams,
  filters: {
    asset?: string;
    orderId?: string;
    foldId?: string;
    start?: string;
    end?: string;
  },
) {
  if (filters.asset) params.set("asset", filters.asset);
  if (filters.orderId) params.set("order_id", filters.orderId);
  if (filters.foldId) params.set("fold_id", filters.foldId);
  if (filters.start) params.set("start", filters.start);
  if (filters.end) params.set("end", filters.end);
}

export const portfolioExecutionApi = {
  catalog: () =>
    getJson<PortfolioExecutionCatalogV4>("/api/v4/portfolio-execution"),
  detail: (validationId: string) =>
    getJson<PortfolioExecutionDetailV4>(
      `/api/v4/portfolio-execution/${encodeURIComponent(validationId)}`,
    ),
  series: (
    validationId: string,
    filters: {
      foldId?: string;
      start?: string;
      end?: string;
      limit?: number;
      offset?: number;
    },
  ) => {
    const params = new URLSearchParams();
    if (filters.foldId) params.set("fold_id", filters.foldId);
    if (filters.start) params.set("start", filters.start);
    if (filters.end) params.set("end", filters.end);
    params.set("limit", String(filters.limit ?? 5000));
    params.set("offset", String(filters.offset ?? 0));
    return getJson<PortfolioSeriesV4>(
      `/api/v4/portfolio-execution/${encodeURIComponent(validationId)}/series?${params.toString()}`,
    );
  },
  analytics: (
    validationId: string,
    filters: {
      asset?: string;
      orderId?: string;
      foldId?: string;
      start?: string;
      end?: string;
      window?: number;
    },
  ) => {
    const params = new URLSearchParams();
    addCommonFilters(params, filters);
    params.set("window", String(filters.window ?? 20));
    return getJson<PortfolioExecutionAnalyticsV4>(
      `/api/v4/portfolio-execution/${encodeURIComponent(validationId)}/analytics?${params.toString()}`,
    );
  },
  decisions: (
    validationId: string,
    filters: {
      asset?: string;
      orderId?: string;
      sessionDate?: string;
      foldId?: string;
      start?: string;
      end?: string;
      limit?: number;
      offset?: number;
    },
  ) => {
    const params = new URLSearchParams();
    addCommonFilters(params, filters);
    if (filters.sessionDate) {
      params.delete("start");
      params.delete("end");
      params.set("session_date", filters.sessionDate);
    }
    params.set("limit", String(filters.limit ?? 5000));
    params.set("offset", String(filters.offset ?? 0));
    return getJson<StrategyDecisionQueryV4>(
      `/api/v4/portfolio-execution/${encodeURIComponent(validationId)}/decisions?${params.toString()}`,
    );
  },
};
