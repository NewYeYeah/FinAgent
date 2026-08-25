# ADR-019 — Phase 5.5 Structured Evidence and Research Memory

Date: 2026-08-25

Status: Accepted

## Context

By Phase 5, FinAgent persists several independently useful evidence domains:

```text
research evidence      hypotheses/features/experiments/results/models
portfolio evidence     health/benchmark/stress/rebalance snapshots
operational evidence   paper orders/fills/reconciliation/shadow/cost evidence
```

The missing capability is not another free-form Agent memory buffer. The system needs an auditable cross-registry lineage that can answer why an idea was tested, what it produced, why similar ideas failed, and how research evidence later behaved in paper/shadow operation.

A vector database alone is unsuitable as the source of truth because nearest-neighbor retrieval does not preserve experiment denominators, immutable identities, exact failure categories, or causal lineage. It can also encourage an Agent to treat semantically similar text as equivalent evidence.

## Decision

Introduce a relational `SQLiteResearchMemoryStore` plus typed `ResearchMemoryService`.

The memory layer stores only cross-registry identities and structured memory records; source registries remain authoritative for their native financial/research state.

```text
ResearchHypothesisRevision
        |
        +--> Generated Feature
        |       |
        |       +--> Experiment
        |               |
        |               +--> Result
        |                       |
        |                       +--> Model
        |                               |
        |                               +--> Portfolio evidence
        |                                       |
        |                                       +--> Paper / Shadow evidence
        |
        +--> normalized FailureRecord
```

## Append-only hypothesis evolution

A hypothesis has a stable `hypothesis_id` and contiguous immutable revisions. Revisions may update statement, rationale, tags or disposition, but old revisions are never overwritten.

Supported dispositions are:

```text
OPEN
SUPPORTED
REJECTED
INCONCLUSIVE
RETIRED
```

This separates evolution of the research claim from deletion of inconvenient history.

## Relational lineage

`MemoryNode` and `LineageEdge` provide a bounded graph over stable identities. Node types include hypothesis, feature, artifact, experiment, result, model, portfolio snapshot, paper order/fill, reconciliation, shadow report and failure.

Edges are immutable and use explicit relations such as:

```text
IMPLEMENTS
TESTED_BY
USES
PRODUCED
PROMOTED_TO
INFORMED
EXECUTED_AS
FILLED_BY
RECONCILED_BY
SHADOWED_BY
FAILED_AS
```

Graph traversal is depth- and node-bounded. The Agent is not allowed to request an unbounded memory dump.

## Failure taxonomy

Phase 5.5 records normalized failures separately from successful evidence. Categories include data, leakage, statistical, model-fit, numerical, cost, turnover, liquidity, risk, execution, reconciliation, operational, policy, duplicate and unknown failures.

A failed experiment remains evidence. Failure history may reduce a later research budget; it is never silently removed from memory.

## Similarity and duplicate detection

The first implementation is deterministic and dependency-light:

- hypothesis similarity uses normalized Latin tokens and CJK bigrams plus tag overlap;
- experiment similarity combines hypothesis, universe, parameter, dataset and code signatures;
- generated-feature similarity combines hypothesis, input-field and lookback overlap.

This is deliberately not advertised as semantic equivalence. Optional embedding retrieval may later complement these signals for papers/reports, but relational IDs and structured evidence remain authoritative.

## Budget recommendation rule

`EvidenceAwareBudgetPolicy` may preserve or reduce a caller-supplied experiment budget. It may never increase it.

```text
requested budget
    |
near duplicate? ------ yes --> 0 new trials / reuse evidence
    |
similar history? ----- yes --> reduce budget
    |
repeated failures? --- yes --> reduce budget
    |
historical winners? --------> no automatic budget expansion
```

This prevents memory from becoming a new route for adaptive data snooping.

## Agent capability boundary

Phase 5.5 adds only read-only memory tools:

```text
list_research_hypotheses
inspect_research_hypothesis
find_similar_hypotheses
inspect_research_lineage
inspect_research_failures
recommend_research_budget
```

No Agent tool can delete memory, rewrite a failure, mutate an old hypothesis revision, expand a research budget, change validation thresholds, alter portfolio state, or change broker/account state.

## Consequences

Positive:

- end-to-end research-to-paper lineage becomes queryable;
- duplicate ideas and repeated failure modes become visible before new experiments;
- Agent context can be bounded and evidence-based instead of free-form history;
- paper/shadow outcomes can be attached to the research artifacts that caused them;
- current research budgets remain governed independently of historical winners.

Trade-offs:

- similarity is lexical/signature based rather than embedding based;
- cross-registry linkage must use stable IDs supplied by deterministic services;
- the memory layer does not replace the research registry, paper broker store or supervision store;
- causal conclusions still require the statistical governance layer, not memory retrieval.
