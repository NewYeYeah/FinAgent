# LIVE-CAPITAL — separate human-governed acceptance

## Goal

Admit a **specific broker/server/account/capital/risk/operational envelope** for small live-capital use after PAPER acceptance.

No research, historical or PAPER result automatically grants this authority.

## Preconditions

- target strategy has R5 `CONFIRMED` evidence;
- target strategy has passed the PAPER stage in the intended broker/account class or an explicitly justified equivalent;
- reconciliation/recovery/safety incidents from PAPER are closed or accepted with explicit limits;
- the human operator explicitly chooses to proceed.

## Deliverables

### 1. Live operating specification

Freeze:

```text
broker/server/account identity
strategy/spec identity
allowed symbols
capital ceiling
per-order/per-symbol/portfolio exposure ceilings
daily loss / drawdown limits
trading hours/session policy
freshness requirements
kill-switch policy
restart/recovery procedure
operator responsibility
credential/secret handling
monitoring/incident retention
```

### 2. Authority model

Agent may:

- explain signals/research context;
- surface anomalies;
- propose research or a future strategy revision.

Agent may not:

- increase capital/risk limits;
- disable safety/reconciliation gates;
- reinterpret unknown broker state as safe;
- silently swap strategy versions;
- self-approve a new live strategy.

Order generation follows the frozen deterministic strategy/controller under human-approved limits.

### 3. Live-specific validation

Confirm:

- actual account/trading permissions;
- contract/margin/financing semantics;
- current source freshness;
- order/fill/deal reconciliation;
- credential isolation;
- restart/incident procedures;
- monitoring and manual kill-switch access.

### 4. Initial capital policy

Begin with the smallest capital/notional envelope that can validate operations. Increasing the envelope is a later explicit operational decision, not a software default.

## Non-goals

- autonomous risk-limit escalation;
- unattended production HA before basic live operations are stable;
- strategy research against live confirmation returns inside the same strategy version;
- automatic promotion of new Agent-generated factors.

## Suggested PR/acceptance structure

Code changes should be small if PAPER architecture is correct. Prefer:

1. live-specific config/authority hardening only where missing;
2. an operator acceptance record/checklist for the exact environment.

Do not create a new parallel trading stack for live.

## Exit gate

Live authority exists only when the exact live operating specification is explicitly approved and all required account, reconciliation, safety, recovery and monitoring checks pass.

Any unknown broker/account/reconciliation state revokes active trading authority until resolved.
