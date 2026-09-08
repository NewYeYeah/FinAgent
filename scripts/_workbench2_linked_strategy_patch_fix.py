from pathlib import Path

patch_path = Path("scripts/_workbench2_linked_strategy_patch.py")
text = patch_path.read_text(encoding="utf-8")
old = '''    '<Link to={`/research-graph${workbenchContextSearch(context)}`}><GitBranch size={13} /> Research Graph</Link>',
    '<Link to={`/research-graph${workbenchContextSearch(context)}`}><GitBranch size={13} /> Research Graph</Link><Link to={`/strategy${workbenchContextSearch(context)}`}>Strategy / terminal</Link>',
'''
new = '''    '<Link to={`/research-graph${workbenchContextSearch(context)}`}>Open Research Graph</Link>',
    '<Link to={`/research-graph${workbenchContextSearch(context)}`}>Open Research Graph</Link><Link to={`/strategy${workbenchContextSearch(context)}`}>Strategy / terminal</Link>',
'''
if old in text:
    text = text.replace(old, new, 1)
patch_path.write_text(text, encoding="utf-8")


def normalize(path: str, old: str, new: str) -> None:
    target = Path(path)
    value = target.read_text(encoding="utf-8")
    if old not in value:
        raise SystemExit(f"normalization anchor missing in {path}: {old[:100]!r}")
    target.write_text(value.replace(old, new, 1), encoding="utf-8")


normalize(
    "docs/development/stages/workbench-2.md",
    "The third vertical slice extends the existing Factor Tear Sheet and adds a first-class Market State surface. It projects only persisted causal MarketState model/state rows, FactorLibrary lifecycle/evaluations, persisted adaptive allocator weight snapshots, Agent audit links and accepted research evidence. React does not fit GMMs, cluster, smooth, infer missing states, recompute factor/economic statistics or create research authority. Missing bindings remain explicitly unavailable/unresolved.",
    "The third vertical slice, `Market State + Factor Intelligence`, is now in Development.",
)
normalize(
    "docs/development/stages/workbench-2.md",
    "5. usability/real-artifact acceptance if not cleanly included in prior slices.",
    "5. human usability if it is not already included in the earlier slices.",
)
normalize(
    "docs/development/backlog.md",
    "The pre-WORKBENCH-2 Agent baseline was audit-oriented. The first WORKBENCH-2 slice reorganized that surface around a research objective/session, Project → Thread → Run navigation, persisted Agent action/result/decision cards, research context, accepted negative terminal state and evidence/config identities. The second slice adds first-class persisted Experiments/comparison and a canonical Research Graph with unresolved-lineage handling. The third slice adds persisted causal MarketState and FactorLibrary intelligence while retaining the existing Factor Tear Sheet. These are implementation milestones only: no fresh task-based human usability baseline has been recorded, so B-101 remains open until the stage's real-artifact human acceptance work is completed.",
    "The first Agent Workspace slice, second Experiments/Research Graph slice, and third Market State/Factor Intelligence slice are implementation milestones only; no fresh real-artifact task-based human usability baseline or acceptance has been executed.",
)
normalize(
    "docs/development/backlog.md",
    "`workspace/src/workbench/query.tsx` still implements cache/stale/in-flight/invalidation behavior for untouched surfaces. The Agent Workspace first slice migrated its touched Agent/Research reads, and the Experiments/Research Graph slice also uses `@tanstack/react-query` for list/detail/comparison/graph/cycle server-state plus SSE-driven graph invalidation. The Market State + Factor Intelligence slice uses TanStack Query for new Market/Factor intelligence reads and migrates the existing touched Factor Tear Sheet server-state calls from the custom query client. Other Workbench consumers remain on the existing wrapper, so B-102 is only partially progressed and remains OPEN; continue migration only when those surfaces are touched for product work.",
    "Agent Workspace + Experiments/Graph + Market/Factor touched server-state reads now use TanStack Query; list/detail/comparison/graph/cycle and Market/Factor reads use TanStack Query, including SSE-driven graph invalidation. The existing Factor Tear Sheet touched server-state was migrated in the third slice. No new custom-query consumer was added.",
)
