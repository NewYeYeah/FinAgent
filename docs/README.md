# FinAgent documentation

The active documentation tree is intentionally small. Its purpose is to let a new developer or Agent recover the project state without reconstructing it from dozens of historical stage documents.

Start with [`../AGENTS.md`](../AGENTS.md).

## Canonical information model

| Need | Read |
| --- | --- |
| Current stage and authority | [`status.toml`](status.toml) |
| End-to-end roadmap | [`development/current-plan.md`](development/current-plan.md) |
| Detailed current/future stage scope | [`development/stages/`](development/stages/) |
| Durable prior progress and negative findings | [`development/history.md`](development/history.md) |
| Open risks, debt and deferred work | [`development/backlog.md`](development/backlog.md) |
| Current architecture | [`architecture/overview.md`](architecture/overview.md) |
| Active architecture/product decisions | [`architecture/decisions.md`](architecture/decisions.md) |
| Test and acceptance policy | [`testing/strategy.md`](testing/strategy.md) |
| Environment and operator workflows | [`guides/`](guides/) |
| Frozen release interpretation | [`releases/`](releases/) |
| Exact implementation history | Git commits and pull requests |

## Active tree

```text
docs/
├── README.md
├── status.toml
├── architecture/
│   ├── overview.md
│   └── decisions.md
├── development/
│   ├── current-plan.md
│   ├── history.md
│   ├── backlog.md
│   └── stages/
│       ├── r3-close.md
│       ├── r4-agent-adaptive.md
│       ├── r5-independent-confirmation.md
│       ├── workbench-2.md
│       ├── paper-trading.md
│       └── live-capital.md
├── guides/
│   ├── getting-started.md
│   ├── data.md
│   ├── research-workflow.md
│   ├── workbench.md
│   └── mt5-paper.md
├── releases/
│   └── ashare-historical-v1.md
└── testing/
    └── strategy.md
```

## Documentation rules

1. `status.toml` contains compact **current facts**, not every historical artifact ID.
2. `current-plan.md` contains the full route and stage relationships, not detailed implementation recipes.
3. Each stage file contains the detailed goal, deliverables, reuse plan, non-goals and exit gate for one stage.
4. `history.md` preserves only completed facts that constrain or inform future work. Exact old protocol details remain in Git/PR history and frozen release records.
5. `backlog.md` is the only active list of unresolved limitations and technical debt.
6. Operator guides describe workflows that can still be run or will directly feed a planned stage. One-off historical stage guides are not retained in the active tree.
7. Architecture documents describe the system **as it exists now**. Future changes belong in stage plans until implemented.
8. A project fact is maintained in one canonical place and linked elsewhere.
9. Documentation is updated in place. Do not create versioned roadmaps, versioned current plans or per-stage changelog files.
10. `python scripts/check_docs.py` enforces structure, required links and compactness.
