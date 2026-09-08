import { expect, test } from "@playwright/test";

const LOCALE_KEY = "finagent.workbench.locale";

const majorRoutes = [
  ["/agent", "智能体"],
  ["/experiments", "实验"],
  ["/research-graph", "研究图谱"],
  ["/market", "市场状态"],
  ["/factors", "因子"],
  ["/strategy", "策略"],
  ["/portfolio", "组合"],
  ["/execution", "执行"],
  ["/catalog", "证据"],
] as const;

test("Workbench bilingual high-contrast smoke preserves route context", async ({ page }) => {
  await page.route("**/api/**", async (route) => {
    await route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "offline i18n/theme smoke" }) });
  });

  // Clear any previous preference exactly once. Re-running this as an init script on
  // every navigation would defeat the locale-persistence contract under test.
  await page.goto("/");
  await page.evaluate((key) => localStorage.removeItem(key), LOCALE_KEY);

  const context = "?run=run-i18n&factor=factor-i18n&experiment=exp-i18n";
  await page.goto(`/agent${context}`);
  const html = page.locator("html");
  await expect(html).toHaveAttribute("data-theme", "high-contrast-dark");
  await expect(html).toHaveAttribute("lang", "en");
  await expect(page.getByRole("navigation", { name: "FinAgent Workbench modules" })).toContainText("Research Graph");
  await expect(page.getByTestId("workbench-context-bar")).toContainText("run-i18n");

  const localeToggle = page.getByTestId("locale-toggle");
  const chinese = localeToggle.getByRole("button", { name: "中文" });
  await chinese.click();
  await expect(html).toHaveAttribute("lang", "zh-CN");
  await expect(page.getByRole("navigation", { name: "FinAgent Workbench 模块" })).toContainText("研究图谱");
  await expect(page).toHaveURL(/\/agent\?run=run-i18n&factor=factor-i18n&experiment=exp-i18n/);
  await expect(page.getByTestId("workbench-context-bar")).toContainText("factor-i18n");
  await expect.poll(() => page.evaluate((key) => localStorage.getItem(key), LOCALE_KEY)).toBe("zh-CN");

  // Verify the actual keyboard-focus contract. :focus-visible is intentionally not
  // asserted for pointer/programmatic focus, so move from 中文 to EN via Shift+Tab.
  await page.keyboard.press("Shift+Tab");
  const english = localeToggle.getByRole("button", { name: "EN" });
  await expect(english).toBeFocused();
  const focusStyle = await english.evaluate((element) => {
    const style = getComputedStyle(element);
    return { outlineStyle: style.outlineStyle, outlineWidth: style.outlineWidth };
  });
  expect(focusStyle.outlineStyle).not.toBe("none");
  expect(Number.parseFloat(focusStyle.outlineWidth)).toBeGreaterThanOrEqual(2);

  for (const [path, label] of majorRoutes) {
    await page.goto(`${path}${context}`);
    const nav = page.getByRole("navigation", { name: "FinAgent Workbench 模块" });
    await expect(nav.getByText(label, { exact: true })).toBeVisible();
    await expect(page).toHaveURL(new RegExp(`${path.replaceAll("/", "\\/")}\\?run=run-i18n`));
    await expect(page.getByTestId("workbench-context-bar")).toContainText("exp-i18n");
  }

  const activeEvidence = page.getByRole("navigation", { name: "FinAgent Workbench 模块" }).getByRole("link", { name: "证据" });
  await expect(activeEvidence).toHaveAttribute("aria-current", "page");
  const selectedStyle = await activeEvidence.evaluate((element) => {
    const style = getComputedStyle(element);
    return { backgroundColor: style.backgroundColor, borderColor: style.borderColor, boxShadow: style.boxShadow };
  });
  expect(selectedStyle.backgroundColor).not.toBe("rgba(0, 0, 0, 0)");
  expect(selectedStyle.borderColor).not.toBe("rgba(0, 0, 0, 0)");

  await page.reload();
  await expect(html).toHaveAttribute("lang", "zh-CN");
  await expect(page.getByRole("navigation", { name: "FinAgent Workbench 模块" })).toContainText("市场状态");
  await expect(page).toHaveURL(/run=run-i18n/);
  await expect(page.getByTestId("workbench-context-bar")).toContainText("exp-i18n");

  await page.getByTestId("locale-toggle").getByRole("button", { name: "EN" }).click();
  await expect(html).toHaveAttribute("lang", "en");
  await expect(page.getByRole("navigation", { name: "FinAgent Workbench modules" })).toContainText("Portfolio");
  await expect(page).toHaveURL(/run=run-i18n/);
});
