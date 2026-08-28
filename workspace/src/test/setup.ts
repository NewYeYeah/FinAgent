import { createElement } from "react";
import "@testing-library/jest-dom/vitest";
import { vi } from "vitest";

// App-level unit tests verify FinAgent routing, evidence semantics and read-only
// behavior. ECharts and React Flow are browser visualization runtimes; their real
// rendering is exercised by the Playwright smoke after the production Vite build.
// Keep jsdom focused on our application contract instead of canvas/layout internals.
vi.mock("echarts-for-react", () => ({
  default: () => createElement("div", { "data-testid": "echarts-mock" }),
}));

vi.mock("@xyflow/react", () => ({
  Background: () => null,
  Controls: () => null,
  MarkerType: { ArrowClosed: "arrowclosed" },
  ReactFlow: ({ children }: { children?: unknown }) =>
    createElement(
      "div",
      { "data-testid": "react-flow-mock" },
      children as ReturnType<typeof createElement>,
    ),
}));

class ResizeObserverMock {
  observe() {}
  unobserve() {}
  disconnect() {}
}

Object.defineProperty(globalThis, "ResizeObserver", {
  configurable: true,
  writable: true,
  value: ResizeObserverMock,
});

Object.defineProperty(window, "matchMedia", {
  configurable: true,
  writable: true,
  value: () => ({
    matches: false,
    media: "",
    onchange: null,
    addListener: () => undefined,
    removeListener: () => undefined,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    dispatchEvent: () => false,
  }),
});
