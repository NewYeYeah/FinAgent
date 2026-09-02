# MT5 broker-clock evidence implementation note

This implementation note records the US-I0/US-D3 clock-domain correction introduced after local `MetaQuotes-Demo` measurements showed that raw `symbol_info_tick().time/time_msc` and MT5 M1 bar timestamps shared a broker wall-clock offset relative to local UTC.

The correction does not assert a broker timezone and does not hard-code the locally observed offset. `MT5BrokerClockEvidence` derives a content-addressed offset from multiple active read-only reference ticks, and quote-probe v2 preserves both the raw broker timestamp and normalized UTC timestamp. Finalization v3 reconstructs and validates that evidence before re-assessing freshness.

Frozen gates are unchanged: 900-second maximum quote age, 60-second maximum future skew after normalization, 50-bps default spread threshold, seed retention, exact mapping attestation, accepted MT5-P0 identity and broker-server consistency. Broker-clock evidence does not rewrite historical research timestamps or MT5-D0 reconciliation evidence.

This note is implementation history only. `docs/status.toml` remains the sole project-stage authority and must not be advanced without reviewed local report identities.
