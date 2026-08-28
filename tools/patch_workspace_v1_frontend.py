from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"missing patch anchor: {path}: {old!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    replace_once(
        "workspace/vite.config.ts",
        'import { defineConfig } from "vite";',
        'import { defineConfig } from "vitest/config";',
    )
    replace_once(
        "workspace/src/App.test.tsx",
        'import App from "./App";\n',
        '''vi.mock("echarts-for-react", () => ({\n  default: () => <div data-testid="echarts" />,\n}));\n\nvi.mock("@xyflow/react", () => ({\n  ReactFlow: ({ children }: { children?: React.ReactNode }) => (\n    <div data-testid="react-flow">{children}</div>\n  ),\n  Background: () => null,\n  Controls: () => null,\n  MarkerType: { ArrowClosed: "arrowclosed" },\n}));\n\nimport App from "./App";\n''',
    )


if __name__ == "__main__":
    main()
