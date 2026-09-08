from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"missing anchor in {path}: {old[:120]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "tests/test_linked_strategy_analytics_v3.py",
    "from pathlib import Path\nfrom typing import Any\n",
    "from pathlib import Path\n",
)

replace_once(
    "workspace/src/workbench/linkedStrategy.test.tsx",
    '''    const panel = await screen.findByRole("region", { name: "Linked strategy analytics" });
    expect(panel).toHaveTextContent("NO_ADAPTIVE_CANDIDATE");
''',
    '''    await screen.findByText("NO_ADAPTIVE_CANDIDATE");
    const panel = screen.getByRole("region", { name: "Linked strategy analytics" });
    expect(panel).toHaveTextContent("NO_ADAPTIVE_CANDIDATE");
''',
)
replace_once(
    "workspace/src/workbench/linkedStrategy.test.tsx",
    '''    const panel = await screen.findByRole("region", { name: "Linked strategy analytics" });
    expect(panel).toHaveTextContent("candidate-a");
''',
    '''    await screen.findByText("candidate-a");
    const panel = screen.getByRole("region", { name: "Linked strategy analytics" });
    expect(panel).toHaveTextContent("candidate-a");
''',
)

replace_once(
    "workspace/src/workbench/strategy.test.tsx",
    '    expect(screen.getByText("Authoritative close-price & execution timeline")).toBeInTheDocument();\n',
    '    expect(await screen.findByText("Authoritative close-price & execution timeline")).toBeInTheDocument();\n',
)

replace_once(
    "workspace/src/workbench/portfolioExecution.test.tsx",
    '    expect(screen.getAllByText(orderId).length).toBeGreaterThan(0);\n',
    '    expect((await screen.findAllByText(orderId)).length).toBeGreaterThan(0);\n',
)

replace_once(
    "workspace/src/workbench/strategyMarketBars.test.tsx",
    'import { cleanup, render, screen, waitFor } from "@testing-library/react";\n',
    'import { QueryClient, QueryClientProvider } from "@tanstack/react-query";\nimport { cleanup, render, screen, waitFor } from "@testing-library/react";\n',
)
replace_once(
    "workspace/src/workbench/strategyMarketBars.test.tsx",
    '''function renderPage() {
  return render(
    <MemoryRouter initialEntries={[`/strategy/${seriesId}?portfolio=${validationId}&asset=${encodeURIComponent(asset)}`]}>
      <WorkbenchQueryProvider>
        <WorkbenchContextProvider>
          <Routes>
            <Route path="/strategy/:seriesId" element={<StrategyDecisionExplorerPage />} />
          </Routes>
        </WorkbenchContextProvider>
      </WorkbenchQueryProvider>
    </MemoryRouter>,
  );
}
''',
    '''function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[`/strategy/${seriesId}?portfolio=${validationId}&asset=${encodeURIComponent(asset)}`]}>
        <WorkbenchQueryProvider>
          <WorkbenchContextProvider>
            <Routes>
              <Route path="/strategy/:seriesId" element={<StrategyDecisionExplorerPage />} />
            </Routes>
          </WorkbenchContextProvider>
        </WorkbenchQueryProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
''',
)
replace_once(
    "workspace/src/workbench/strategyMarketBars.test.tsx",
    '''      if (url === "/api/v4/strategy-series") return json({
        schema_version: "finagent.strategy-explorer.catalog.v1",
        read_only: true,
        items: [item],
        warnings: [],
        notices: [],
      });
''',
    '''      if (url === "/api/v4/strategy-series") return json({
        schema_version: "finagent.strategy-explorer.catalog.v1",
        read_only: true,
        items: [item],
        warnings: [],
        notices: [],
      });
      if (url === "/api/v3/linked-strategy") return json({
        schema_version: "linked",
        items: [],
        default_cycle_id: null,
        historical_strategy_series_count: 1,
        historical_strategy_relation: "unbound_unless_explicit_candidate_binding",
        read_only: true,
        canonical_identity_only: true,
        browser_recomputation: false,
        hidden_reasoning: "not_persisted_not_projected",
      });
''',
)

print("linked strategy first CI fixes applied")
