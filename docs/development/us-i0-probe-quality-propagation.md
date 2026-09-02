# US-I0 probe-quality propagation fix

This implementation note records a diagnostic-only correction discovered from local post-clock-normalization evidence.

Candidate quote-probe v2 already classified probe-time `stale_quote` and `future_quote` issues correctly. Finalizer v3 previously re-assessed only symbols that were valid at probe time, so quotes already rejected for freshness at probe time did not appear in the final `stale_quote_symbols` / `future_quote_symbols` or `excluded_by_quote_quality` diagnostics.

The fix preserves probe-time stale/future classifications in the v3 evidence assessment and still rechecks probe-valid quotes at finalization time. It does not change the 900-second quote-age gate, 60-second future-skew gate, spread threshold, seed retention, broker-clock normalization, or any stage authority.
