export interface MarketBarBindingAC2 {
  schema_version: string;
  read_only: true;
  browser_recomputation: false;
  authority: "authoritative";
  series_id: string;
  interval: string;
  timestamp_convention: string;
  source_identity: string;
  data_version: string;
  row_count: number;
  asset_count: number;
  session_count: number;
  session_spec: {
    market_id: string;
    timezone: string;
    segments: Array<{
      name: string;
      start: string;
      end: string;
      session_type: string;
    }>;
  };
  label_horizon_policy: {
    mode: string;
    value: number;
    allow_cross_session: boolean;
  };
}

export interface MarketBarRowAC2 {
  sequence: number;
  row_id: string;
  asset: string;
  session_date: string;
  event_time: string;
  available_at: string;
  interval: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  session_id: string;
  session_type: string;
  source: string;
  data_version: string;
}

export interface MarketBarQueryAC2 {
  schema_version: string;
  read_only: true;
  authority: "authoritative";
  series_id: string;
  linked_strategy_series_id: string;
  portfolio_validation_id: string;
  interval: string;
  timestamp_convention: string;
  session_spec: MarketBarBindingAC2["session_spec"];
  label_horizon_policy: MarketBarBindingAC2["label_horizon_policy"];
  filters: {
    asset: string | null;
    start: string | null;
    end: string | null;
    limit: number;
    offset: number;
  };
  total: number;
  items: MarketBarRowAC2[];
}

const API_BASE = (import.meta.env.VITE_API_BASE ?? "").replace(/\/$/, "");

async function errorFrom(response: Response): Promise<Error> {
  let detail = `${response.status} ${response.statusText}`;
  try {
    const payload = (await response.json()) as { detail?: string };
    if (payload.detail) detail = payload.detail;
  } catch {
    // Preserve the HTTP fallback when the response is not JSON.
  }
  return new Error(detail);
}

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: "GET",
    headers: { Accept: "application/json" },
  });
  if (!response.ok) throw await errorFrom(response);
  return (await response.json()) as T;
}

export const marketBarApi = {
  binding: (strategySeriesId: string) =>
    getJson<MarketBarBindingAC2>(
      `/api/v4/strategy-series/${encodeURIComponent(strategySeriesId)}/market-bar-binding`,
    ),
  bars: (
    strategySeriesId: string,
    filters: {
      asset?: string;
      start?: string;
      end?: string;
      limit?: number;
      offset?: number;
    },
  ) => {
    const params = new URLSearchParams();
    if (filters.asset) params.set("asset", filters.asset);
    if (filters.start) params.set("start", filters.start);
    if (filters.end) params.set("end", filters.end);
    params.set("limit", String(filters.limit ?? 1000));
    params.set("offset", String(filters.offset ?? 0));
    return getJson<MarketBarQueryAC2>(
      `/api/v4/strategy-series/${encodeURIComponent(strategySeriesId)}/market-bars?${params.toString()}`,
    );
  },
};
