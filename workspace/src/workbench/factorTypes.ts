export type FactorMetricAuthorityV4 = "authoritative" | "derived";

export interface FactorSeriesItemV4 {
  series_id: string;
  program_result_id: string;
  program_id: string;
  selection_id: string;
  data_version: string;
  candidate_feature_digests: string[];
  selected_feature_digests: string[];
  primary_label: string;
  decay_labels: string[];
  quantiles: number;
  row_count: number;
  factor_count: number;
  fold_count: number;
  session_count: number;
  start_date: string | null;
  end_date: string | null;
  source_report_content_digest: string;
  authority: "authoritative";
  detail_url: string;
}

export interface FactorSeriesCatalogV4 {
  schema_version: string;
  read_only: true;
  items: FactorSeriesItemV4[];
  warnings: string[];
  notices: string[];
}

export interface FactorSeriesManifestV4 {
  schema_version: string;
  authority: "authoritative";
  series_id: string;
  program_result_id: string;
  program_id: string;
  program_spec_id: string;
  walk_forward_report_id: string;
  gate_report_id: string;
  selection_id: string;
  plan_id: string;
  data_version: string;
  candidate_selection_id: string;
  universe_policy_version: string;
  candidate_feature_digests: string[];
  selected_feature_digests: string[];
  primary_label: string;
  decay_labels: string[];
  quantiles: number;
  min_cross_section: number;
  min_periods: number;
  annualization: number;
  winsor_lower_quantile: number;
  winsor_upper_quantile: number;
  rolling_window: number;
  quant_config_digest: string;
  rows_digest: string;
  source_report_content_digest: string;
  source_report_file: string;
  source_report_sha256: string;
  data_file: string;
  data_sha256: string;
  row_count: number;
  factor_count: number;
  fold_count: number;
  session_count: number;
  start_date: string | null;
  end_date: string | null;
  columns: string[];
  nullable_columns: string[];
  metric_authority: {
    authoritative: string[];
    derived: string[];
  };
}

export interface FactorSeriesDetailV4 {
  schema_version: string;
  read_only: true;
  item: FactorSeriesItemV4;
  manifest: FactorSeriesManifestV4;
  presentation: {
    browser_recomputation: false;
    period_evidence: string;
    statistical_summary: string;
    derived_metrics: string[];
  };
}

export interface FactorDimensionV4 {
  feature_digest: string;
  feature_id: string;
  selected: boolean;
}

export interface FactorSeriesDimensionsV4 {
  schema_version: string;
  read_only: true;
  series_id: string;
  program_id: string;
  program_result_id: string;
  factors: FactorDimensionV4[];
  folds: string[];
  labels: string[];
  primary_label: string;
  decay_labels: string[];
  quantiles: number[];
  start_date: string | null;
  end_date: string | null;
  session_count: number;
  metric_authority: {
    authoritative: string[];
    derived: string[];
  };
}

export interface FactorSeriesRowV4 {
  sequence: number;
  row_id: string;
  feature_id: string;
  feature_digest: string;
  fold_id: string;
  session_date: string;
  train_direction: number;
  series_kind: "coverage" | "ic" | "quantile" | "long_short" | "turnover";
  metric: string;
  authority: FactorMetricAuthorityV4;
  label_name: string;
  quantile: number | null;
  value: number;
  sample_count: number;
  window_count: number;
}

export interface FactorSeriesQueryV4 {
  schema_version: string;
  read_only: true;
  authority: "mixed_persisted_metrics";
  series_id: string;
  program_result_id: string;
  total: number;
  offset: number;
  limit: number;
  items: FactorSeriesRowV4[];
}

export interface FrozenFactorFoldV4 {
  fold_id: string;
  train_direction?: number;
  train_rank_ic?: number;
  train_rank_icir?: number;
  test_raw_rank_ic?: number;
  test_raw_rank_icir?: number;
  test_rank_ic?: number;
  test_rank_icir?: number;
  test_raw_long_short_sharpe?: number;
  test_long_short_sharpe?: number;
  coverage?: number;
  quantile_monotonicity?: number;
  mean_one_way_turnover?: number;
  periods?: number;
  [key: string]: unknown;
}

export interface FrozenFactorStatisticsV4 {
  dominant_direction?: number;
  direction_consistency?: number;
  pooled_rank_ic?: number;
  pooled_rank_icir?: number;
  mean_fold_rank_icir?: number;
  worst_fold_rank_icir?: number;
  positive_fold_ratio?: number;
  mean_fold_long_short_sharpe?: number;
  worst_fold_long_short_sharpe?: number;
  coverage_mean?: number;
  coverage_min?: number;
  quantile_monotonicity?: number;
  mean_one_way_turnover?: number;
  horizon_sign_consistency?: number;
  hac_tstat?: number;
  raw_hac_pvalue?: number;
  bootstrap_pvalue?: number;
  bootstrap_ci_lower?: number;
  bootstrap_ci_upper?: number;
  holm_adjusted_pvalue?: number;
  bh_qvalue?: number;
  [key: string]: unknown;
}

export interface FrozenFactorSummaryItemV4 {
  feature_id: string;
  feature_digest: string;
  selected: boolean;
  statistics: FrozenFactorStatisticsV4;
  folds: FrozenFactorFoldV4[];
  gate: Record<string, unknown> | null;
  selection_component: Record<string, unknown> | null;
}

export interface FactorSeriesSummaryV4 {
  schema_version: string;
  read_only: true;
  authority: "authoritative_frozen_a2p6_summary";
  statistics_recomputed: false;
  series_id: string;
  program_id: string;
  program_result_id: string;
  items: FrozenFactorSummaryItemV4[];
  factor_value_correlations: Record<string, number>;
  selection: Record<string, unknown>;
}
