export interface StrategySeriesItemV4 {
  series_id: string;
  portfolio_validation_id: string;
  source_program_result_id: string;
  source_selection_id: string;
  data_version: string;
  selected_feature_digests: string[];
  alpha_model_ids: string[];
  row_count: number;
  session_count: number;
  asset_count: number;
  start_date: string | null;
  end_date: string | null;
  authority: "authoritative";
  detail_url: string;
}

export interface StrategySeriesCatalogV4 {
  schema_version: string;
  read_only: true;
  items: StrategySeriesItemV4[];
  warnings: string[];
  notices: string[];
}

export interface StrategySeriesManifestV4 {
  schema_version: string;
  authority: "authoritative";
  series_id: string;
  portfolio_validation_id: string;
  a4_spec_id: string;
  source_program_result_id: string;
  source_program_spec_id: string;
  source_program_report_digest: string;
  source_selection_id: string;
  data_version: string;
  execution_ledger_digest: string;
  selected_feature_digests: string[];
  alpha_model_ids: string[];
  rows_digest: string;
  source_report_file: string;
  source_report_sha256: string;
  source_ledger_file: string;
  source_ledger_sha256: string;
  data_file: string;
  data_sha256: string;
  row_count: number;
  source_session_count: number;
  row_session_count: number;
  asset_count: number;
  start_date: string | null;
  end_date: string | null;
  columns: string[];
  nullable_columns: string[];
}

export interface StrategySeriesDetailV4 {
  schema_version: string;
  read_only: true;
  item: StrategySeriesItemV4;
  manifest: StrategySeriesManifestV4;
  presentation: {
    price_semantics: "authoritative_close_only";
    ohlc_available: false;
    browser_recomputation: false;
    factor_contribution_semantics: string;
  };
}

export interface StrategySeriesDimensionsV4 {
  schema_version: string;
  read_only: true;
  authority: "authoritative";
  series_id: string;
  portfolio_validation_id: string;
  assets: string[];
  folds: string[];
  start_date: string | null;
  end_date: string | null;
  session_count: number;
  price_semantics: string;
  ohlc_available: false;
}

export interface StrategyDecisionRowV4 {
  sequence: number;
  row_id: string;
  fold_id: string;
  session_date: string;
  signal_asof: string;
  asset: string;
  rebalanced: boolean;
  cash_fallback: boolean;
  target_id: string;
  alpha_score: number | null;
  alpha_rank: number | null;
  alpha_expected_return: number | null;
  alpha_uncertainty: number | null;
  pre_trade_weight: number | null;
  target_weight: number | null;
  realized_weight: number;
  desired_side: string | null;
  desired_quantity: number;
  executable_quantity: number;
  filled_quantity: number;
  reference_price: number | null;
  fill_price: number | null;
  close_price: number | null;
  fees: number;
  slippage: number;
  gross_pnl: number;
  net_pnl: number;
  decision_status: string | null;
  client_order_id: string | null;
  constraint_codes: string[];
}

export interface StrategyDecisionQueryV4 {
  schema_version: string;
  read_only: true;
  authority: "authoritative";
  series_id: string;
  portfolio_validation_id: string;
  filters: {
    asset: string | null;
    start: string | null;
    end: string | null;
    fold_id: string | null;
    limit: number;
    offset: number;
  };
  total: number;
  items: StrategyDecisionRowV4[];
}
