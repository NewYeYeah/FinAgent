export interface PortfolioExecutionItemV4 {
  portfolio_validation_id: string;
  strategy_series_id: string;
  source_program_result_id: string;
  source_selection_id: string;
  row_count: number;
  asset_count: number;
  fold_count: number;
  session_count: number;
  start_date: string | null;
  end_date: string | null;
  status: string;
  authority: string;
  detail_url: string;
}

export interface PortfolioExecutionCatalogV4 {
  schema_version: string;
  read_only: boolean;
  items: PortfolioExecutionItemV4[];
  warnings: string[];
}

export interface PortfolioMetricsV4 {
  gross_return: number;
  net_return: number;
  gross_annualized_return: number;
  net_annualized_return: number;
  gross_sharpe: number;
  net_sharpe: number;
  max_drawdown: number;
  gross_to_net_drag: number;
  one_way_turnover: number;
  implementation_shortfall: number;
  cash_fallback_ratio: number;
  rejected_order_ratio: number;
  maximum_ex_post_participation: number;
  authority: string;
}

export interface PortfolioExecutionDetailV4 {
  schema_version: string;
  read_only: boolean;
  item: PortfolioExecutionItemV4;
  portfolio_metrics: PortfolioMetricsV4;
  economic_evidence: Record<string, unknown>;
  folds: Array<Record<string, unknown>>;
  ledger: Record<string, unknown>;
  authority: Record<string, string>;
  presentation: {
    browser_recomputation: boolean;
    drawdown: string;
    rolling: string;
    monthly_returns: string;
    filtered_costs: string;
    constraint_counts: string;
    target_realized: string;
    benchmark_available: boolean;
    order_id_available: boolean;
    benchmark_note: string;
    order_identity_note: string;
  };
}

export interface PortfolioSeriesPointV4 {
  session_date: string;
  fold_id: string;
  net_nav: number;
  gross_nav: number;
  net_return: number;
  gross_return: number;
  authority: string;
}

export interface PortfolioSeriesV4 {
  schema_version: string;
  read_only: boolean;
  authority: string;
  portfolio_validation_id: string;
  total: number;
  offset: number;
  limit: number;
  items: PortfolioSeriesPointV4[];
}

export interface DrawdownPointV4 {
  session_date: string;
  fold_id: string;
  net_drawdown: number;
  gross_drawdown: number;
}

export interface RollingPointV4 {
  session_date: string;
  fold_id: string;
  window_periods: number;
  rolling_return: number;
  rolling_volatility: number;
  rolling_sharpe: number;
}

export interface MonthlyReturnV4 {
  month: string;
  year: number;
  month_number: number;
  net_return: number;
  gross_return: number;
  periods: number;
}

export interface PortfolioExecutionAnalyticsV4 {
  schema_version: string;
  read_only: boolean;
  portfolio_validation_id: string;
  filters: {
    asset: string | null;
    order_id: string | null;
    fold_id: string | null;
    start: string | null;
    end: string | null;
    window: number;
  };
  drawdown: {
    authority: string;
    source_authority: string;
    formula: string;
    items: DrawdownPointV4[];
  };
  rolling: {
    authority: string;
    source_authority: string;
    annualization: number;
    window: number;
    items: RollingPointV4[];
  };
  monthly_returns: {
    authority: string;
    source_authority: string;
    formula: string;
    items: MonthlyReturnV4[];
  };
  filtered_costs: {
    authority: string;
    source_authority: string;
    fees: number;
    slippage: number;
    total_cost: number;
    decision_row_count: number;
  };
  order_funnel: {
    authority: string;
    source_authority: string;
    desired: number;
    executable: number;
    filled: number;
    decision_status_counts: Record<string, number>;
    order_id_available: boolean;
  };
  constraint_attribution: {
    authority: string;
    source_authority: string;
    reason_counts: Record<string, number>;
  };
  benchmark: {
    available: boolean;
    authority: string;
    note: string;
  };
}

export interface StrategyDecisionRowV4 {
  row_id: string;
  schema_version: string;
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
  read_only: boolean;
  authority: string;
  series_id: string;
  total: number;
  offset: number;
  limit: number;
  items: StrategyDecisionRowV4[];
}
