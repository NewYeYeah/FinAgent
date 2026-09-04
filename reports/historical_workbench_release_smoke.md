# Historical Workbench 1.0 Post-freeze Release Smoke

- Smoke ID: `historical-workbench-rs-7ad4e7bdfa86b3551da62c6691934933bc312c73`
- Freeze ID: `ashare-historical-v1-76ba98983c1ffc6efb4b0f9a16acd5192eb7dd6c`
- Freeze Git SHA: `52856ce69fb713d486c0476117528d4c86fcb9a7`
- Smoke Git SHA: `977cb8c80a84329a6bb227734ef0e1de9a51014a`
- Research outcome: `NO_ROBUST_FACTOR_FAMILY`
- Contract valid: `true`
- Browser: `passed`
- Accepted: `true`

## Frozen identities

- program_result_id: `ashare-robust-program-result-538f8ba57118c43a8b900d82`
- portfolio_validation_id: `ashare-portfolio-validation-5d39439bfe9d0c29dde1d62b`
- strategy_series_id: `strategy-decision-series-2c03e7a65b43ffc5a3fb68d0a3b5910fd000370e`
- factor_series_id: `factor-series-a65bbb2ffbdc5adc14a53ade737b5fecb31ddc98`
- market_bar_series_id: `None`

## Checks

- `configuration_surface_available`: `true`
- `control_plane_not_embedded`: `true`
- `evidence_plane_enabled`: `true`
- `factor_identity_exact`: `true`
- `freeze_identity_recomputed`: `true`
- `freeze_package_embeds_exact_records`: `true`
- `freeze_release_is_ancestor`: `true`
- `linked_analytics_accepted`: `true`
- `linked_missing_evidence_policy`: `true`
- `linked_no_browser_recompute`: `true`
- `no_alpha_execution_not_fabricated`: `true`
- `no_alpha_factor_evidence_visible`: `true`
- `no_alpha_market_bars_unavailable`: `true`
- `no_alpha_portfolio_explicit_unavailable`: `true`
- `no_alpha_strategy_dimensions_empty`: `true`
- `no_alpha_strategy_explicit_empty`: `true`
- `strategy_identity_exact`: `true`
- `strategy_portfolio_binding_exact`: `true`
- `workbench_product_unchanged_since_freeze`: `true`
- `workbench_read_only`: `true`

## Boundary

This smoke is read-only. It does not rerun research, consume the production reserve, create orders, enable PAPER or authorize live capital.
