# ADR-017 — Phase 4.5 Low-Permission Portfolio Supervisor

Date: 2026-08-25

Status: Accepted

## Context

Phase 4 made expected-return calibration, risk estimation, portfolio constraints, benchmark construction, stress testing and rebalance decisions deterministic. The next Agent capability therefore must supervise those outputs without becoming a second optimizer or a bypass around `RiskGate`.

A portfolio-facing LLM/Agent has a materially different risk profile from the research Agent. Research mistakes can waste compute or contaminate evidence; portfolio mistakes can change financial state. The Phase 4.5 surface is therefore narrower than the Phase 3 research surface.

## Decision

Introduce an immutable `PortfolioHealthSnapshot` and a separate low-permission Supervisor policy/tool surface.

```text
Phase 4 outputs
  AlphaForecast / RiskForecast
  PortfolioBenchmarkSuite
  StressTestReport
  RebalanceDecision
        |
        v
PortfolioHealthMonitor
        |
PortfolioHealthSnapshot
        |
SQLitePortfolioSupervisionStore
        |
Portfolio Supervisor tools
        |
PortfolioSupervisorPolicy
        |
ScriptedPortfolioSupervisorAgent
```

The Supervisor can inspect health, benchmark, stress and rebalance evidence; list pre-registered operating policies; and create non-mutating requests for policy changes, rebalances or human review.

## Hard capability boundary

The Supervisor tool registry does not contain capabilities to:

```text
set arbitrary portfolio weights
change hard risk limits
bypass RiskGate
choose fill prices
submit broker orders
mutate account/broker state
alter alpha or covariance estimates
rewrite statistical evidence
```

`REQUEST_OPERATING_POLICY` and `REQUEST_REBALANCE` are `ToolMode.REQUEST`. `PortfolioSupervisorPolicy` returns `REQUIRE_HUMAN`, so handlers may validate domain legality and materialize an exact review payload but must return `mutation_performed=false`.

A human approval outside the Agent runtime is therefore required before an operational controller can apply the request.

## Health snapshot

`PortfolioHealthMonitor` converts deterministic Phase 4 outputs into immutable supervision evidence. Checks include:

```text
forecast/state clock alignment
data freshness
forecast freshness
selected expected net return
selected forecast volatility
selected turnover
worst configured stress loss
existing deterministic rebalance decision
```

Thresholds are configuration, not LLM outputs. Optional thresholds are explicit; the monitor does not silently invent portfolio limits.

The snapshot also persists common constructor metrics, scenario returns and the largest target/current weight drifts so an Agent can explain why a target changed without receiving weight-writing authority.

## Operating policies

`OperatingPolicyRegistry` contains pre-registered policy identities such as:

```text
normal
cautious
defensive
paused
```

A policy references deterministic constraint/rebalance policy identifiers. The Supervisor can request one of these identities; it cannot synthesize new constraint values.

## Reference runtime

`ScriptedPortfolioSupervisorAgent` is the deterministic Phase 4.5 acceptance runtime:

```text
inspect health
inspect benchmark suite
inspect stress report
inspect rebalance decision
list operating policies

if CRITICAL:
    request defensive policy
    request human review
elif WARNING and deterministic rebalance=True:
    request rebalance
elif WARNING:
    request human review
else:
    no action
```

This runtime intentionally proves the governance path without relying on LLM judgement. A future explanatory LLM adapter may consume the same immutable snapshot and finite tools, but it does not need a broader authority surface.

## Persistence and audit

`SQLitePortfolioSupervisionStore` stores snapshots immutably. Existing `SQLiteAgentAuditStore` records every Supervisor tool request, policy decision and result. Request payloads are replayable and explicitly report that no financial-state mutation occurred.

## Consequences

Positive:

- portfolio supervision becomes auditable and testable;
- health thresholds remain deterministic configuration;
- policy/rebalance requests are separated from their application;
- Agent explanations can be grounded in benchmark/stress/drift evidence;
- Phase 5 can attach an operational approval controller without widening Agent permissions.

Trade-offs:

- Phase 4.5 does not automatically execute defensive modes or rebalances;
- the reference Supervisor is deterministic rather than an LLM decision-maker;
- operational policy application, broker state and kill switches remain Phase 5 work.
