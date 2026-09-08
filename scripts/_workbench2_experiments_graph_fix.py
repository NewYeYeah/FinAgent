from pathlib import Path


def replace(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"patch anchor missing: {path}: {old[:100]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


replace(
    "workspace/src/workbench/experiments.tsx",
    '      <small>{identity(item.allocator)} · {identity(item.factor_set_id)}</small>\n',
    '      <small>{identity(item.allocator)} · {identity(item.factor_set_id)}</small>\n      {item.error ? <small className="experiment-negative-detail">{item.error}</small> : null}\n',
)
replace(
    "workspace/src/workbench/researchGraph.tsx",
    'import { useWorkbenchContext, workbenchContextSearch, type WorkbenchContextState } from "./context";\n',
    'import { patchWorkbenchContext, useWorkbenchContext, workbenchContextSearch, type WorkbenchContextState } from "./context";\n',
)
replace(
    "workspace/src/workbench/researchGraph.tsx",
    '    select(canonicalPatch(canonical), "graph_node_selected");\n    if (canonical.href) navigate(canonical.href);\n',
    '    const patch = canonicalPatch(canonical);\n    const nextContext = patchWorkbenchContext(context, patch);\n    select(patch, "graph_node_selected");\n    if (canonical.href) {\n      const target = new URL(canonical.href, window.location.origin);\n      navigate({ pathname: target.pathname, search: workbenchContextSearch(nextContext) });\n    }\n',
)
