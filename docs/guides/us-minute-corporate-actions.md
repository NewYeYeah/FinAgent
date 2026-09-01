# U.S. minute corporate-action authority

US-D2 deliberately separates **raw intraday price authority** from **corporate-action coverage and adjusted research prices**.

The admitted `mito0o852/OHLCV-1m` snapshot is raw/split-unadjusted intraday OHLCV and contains no embedded, certified corporate-action feed. FinAgent therefore does not infer splits/dividends from price jumps and does not advertise split-adjusted or total-return-adjusted query capability.

## Current source evidence

The bound local snapshot receives a `CorporateActionCoverageEvidence` whose status is:

```text
UNAVAILABLE
```

It binds the exact OHLCV source/revision and retains limitations:

```text
corporate_actions:not_embedded_in_ohlcv
adjusted_prices:not_authoritative
cross_session_raw_continuity:not_authoritative_without_action_coverage
```

An unavailable coverage object cannot carry events or claim covered action types.

## Research authority policy

Current v1 policy narrows research rather than fabricating a transform:

```text
same-session RAW
→ allowed without action coverage

cross-session RAW
→ requires complete coverage for split + cash-dividend + cash-event types
→ if a covered action occurs between the two prices, raw continuity is rejected

SPLIT_ADJUSTED
→ requires split coverage
→ still rejected because the transform is not implemented/certified

TOTAL_RETURN_ADJUSTED
→ requires complete split/cash coverage
→ still rejected because the transform is not implemented/certified
```

The first strategy and canonical 60-trading-minute label remain same-session, so this narrowed authority is sufficient for the first intraday Alpha Gate while preserving the missing-action limitation.

## Coverage interval semantics

Corporate-action continuity checks use `(start, end]`: an action effective exactly at the target timestamp can affect the target price and is therefore included.

`CorporateActionCoverageEvidence` validates:

- asset set and UTC coverage interval;
- source/revision identity;
- declared covered event types;
- event asset membership;
- event effective time inside coverage;
- deterministic event ordering/content-addressed coverage identity.

## Synthetic regression

Synthetic coverage fixtures demonstrate the future contract without claiming a real action provider:

- complete declared coverage with no event can prove raw cross-session continuity;
- split, cash-dividend or cash-event between two raw prices rejects continuity;
- adjusted-price requests remain fail-closed even under synthetic complete coverage because no certified transform exists;
- coverage identity is independent of input asset/event order;
- undeclared event types are rejected.

These fixtures are contract tests only. They do not upgrade the real OHLCV source's corporate-action authority.
