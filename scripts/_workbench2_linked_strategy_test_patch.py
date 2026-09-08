from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"missing test anchor in {path}: {old[:100]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


empty_linked = '''      if (url === "/api/v3/linked-strategy") return json({ schema_version: "linked", items: [], default_cycle_id: null, historical_strategy_series_count: 1, historical_strategy_relation: "unbound_unless_explicit_candidate_binding", read_only: true, canonical_identity_only: true, browser_recomputation: false, hidden_reasoning: "not_persisted_not_projected" });\n'''

replace_once(
    "workspace/src/workbench/strategy.test.tsx",
    'import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";\n',
    'import { QueryClient, QueryClientProvider } from "@tanstack/react-query";\nimport { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";\n',
)
replace_once(
    "workspace/src/workbench/strategy.test.tsx",
    '''function renderPage(initial = `/strategy/${seriesId}?portfolio=${validationId}&asset=${encodeURIComponent(asset)}`) {
  return render(
    <MemoryRouter initialEntries={[initial]}>
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
    '''function renderPage(initial = `/strategy/${seriesId}?portfolio=${validationId}&asset=${encodeURIComponent(asset)}`) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initial]}>
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
    "workspace/src/workbench/strategy.test.tsx",
    '      if (url === "/api/v4/strategy-series") return json(catalog);\n',
    '      if (url === "/api/v4/strategy-series") return json(catalog);\n' + empty_linked,
)

empty_linked_portfolio = empty_linked.replace("return json(", "return response(")
replace_once(
    "workspace/src/workbench/portfolioExecution.test.tsx",
    'import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";\n',
    'import { QueryClient, QueryClientProvider } from "@tanstack/react-query";\nimport { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";\n',
)
replace_once(
    "workspace/src/workbench/portfolioExecution.test.tsx",
    '''function renderPage(initial: string) {
  return render(
    <MemoryRouter initialEntries={[initial]}>
      <WorkbenchQueryProvider>
        <WorkbenchContextProvider>
          <LocationProbe />
          <Routes>
            <Route path="/portfolio/:validationId" element={<PortfolioInteractivePage />} />
            <Route path="/execution/:validationId" element={<ExecutionInteractivePage />} />
          </Routes>
        </WorkbenchContextProvider>
      </WorkbenchQueryProvider>
    </MemoryRouter>,
  );
}
''',
    '''function renderPage(initial: string) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initial]}>
        <WorkbenchQueryProvider>
          <WorkbenchContextProvider>
            <LocationProbe />
            <Routes>
              <Route path="/portfolio/:validationId" element={<PortfolioInteractivePage />} />
              <Route path="/execution/:validationId" element={<ExecutionInteractivePage />} />
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
    "workspace/src/workbench/portfolioExecution.test.tsx",
    '      if (url === "/api/v4/portfolio-execution") return response(catalog);\n',
    '      if (url === "/api/v4/portfolio-execution") return response(catalog);\n' + empty_linked_portfolio,
)

print("linked strategy legacy test harness patched")
