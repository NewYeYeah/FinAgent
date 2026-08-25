# Phase 5.5 — Structured Evidence and Research Memory

Phase 5.5 converts FinAgent's accumulated registries into bounded, auditable research memory. It is not a chat-history store and it does not grant the Agent new financial authority.

## Delivered components

```text
src/finagent/memory/domain.py
  ResearchHypothesisRevision
  HypothesisDisposition
  MemoryNode / MemoryNodeType
  LineageEdge / LineageRelation
  FailureRecord / FailureCategory / FailureStage
  SimilarityMatch
  MemoryGraph
  ResearchMemorySummary
  BudgetRecommendation

src/finagent/memory/store.py
  SQLiteResearchMemoryStore

src/finagent/memory/service.py
  ResearchMemoryService
  EvidenceAwareBudgetPolicy

src/finagent/agents/tools/memory.py
  bounded read-only Agent memory tools
```

## Hypothesis lifecycle

Hypotheses are append-only revisions under one stable ID.

```text
hypothesis h, revision 1
        |
        v
hypothesis h, revision 2
        |
        v
hypothesis h, revision 3
```

Revision numbers must be contiguous. Re-registering the exact same revision is idempotent; changing an existing revision is rejected.

## Evidence graph

The memory store records stable identities rather than copying all source-registry payloads.

```text
hypothesis
  -> feature
  -> experiment
  -> result
  -> model
  -> portfolio snapshot
  -> paper order/fill
  -> reconciliation/shadow evidence
```

`ResearchMemoryService.register_operational_outcome()` permits deterministic services to attach paper/shadow evidence to an already registered research/model lineage. The memory graph therefore answers provenance questions without becoming the financial-state system of record.

## Failure memory

Failure evidence is normalized by category and stage. Examples:

```text
TURNOVER / VALIDATION
LIQUIDITY / PORTFOLIO
EXECUTION / EXECUTION
RECONCILIATION / RECONCILIATION
POLICY / OPERATIONAL
```

Failures are immutable and queryable by hypothesis, experiment or category.

## Similarity

The initial similarity layer is deterministic:

```text
hypothesis  -> text/tag Jaccard
experiment  -> hypothesis + universe + params + dataset + code signature
feature     -> hypothesis + input fields + lookback
```

This is a duplicate-search aid, not proof that two strategies are economically equivalent.

## Evidence-aware budget policy

The caller supplies the maximum allowed experiment count. Memory can only reduce it.

Near-duplicate evidence may reduce the recommendation to zero new experiments. Similar prior hypotheses or repeated failures can reduce the budget. Historical successes never increase the requested budget.

This preserves the Phase 2.5 principle that research multiplicity cannot be retroactively expanded because previous results looked promising.

## Bounded Agent memory tools

Read-only tools:

```text
list_research_hypotheses
inspect_research_hypothesis
find_similar_hypotheses
inspect_research_lineage
inspect_research_failures
recommend_research_budget
```

All result surfaces have explicit limits. There is no Agent memory-delete or historical-rewrite tool.

## Validation focus

Phase 5.5 tests cover:

- contiguous append-only hypothesis revision;
- immutable nodes and edges;
- research -> result -> portfolio -> paper lineage;
- normalized failure taxonomy;
- deterministic duplicate-hypothesis detection;
- experiment-signature similarity;
- budget non-expansion and duplicate blocking;
- bounded graph truncation;
- read-only Agent memory tool surface.

## Deferred

Phase 5.5 does not add:

```text
embedding/vector database as source of truth
unbounded autonomous reflection
automatic hypothesis generation from memory
automatic budget expansion
memory-driven validation-threshold changes
live broker integration
```

Optional semantic retrieval can later be added for unstructured papers and reports, but it should reference structured memory identities rather than replace them.
