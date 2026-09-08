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
  await page.addInitScript((key) => window.localStorage.removeItem(key), LOCALE_KEY);
  await page.route("**/api/**", async (route) => {
    await route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "offline i18n/theme smoke" }) });
  });

  const context = "?run=run-i18n&factor=factor-i18n&experiment=exp-i18n";
  await page.goto(`/agent${context}`);
  const html = page.locator("html");
  await expect(html).toHaveAttribute("data-theme", "high-contrast-dark");
  await expect(html).toHaveAttribute("lang", "en");
  await expect(page.getByRole("navigation", { name: "FinAgent Workbench modules" })).toContainText("Research Graph");
  await expect(page.getByTestId("workbench-context-bar")).toContainText("run-i18n");

  const chinese = page.getByTestId("locale-toggle").getByRole("button", { name: "中文" });
  await chinese.click();
  await expect(html).toHaveAttribute("lang", "zh-CN");
  await expect(page.getByRole("navigation", { name: "FinAgent Workbench 模块" })).toContainText("研究图谱");
  await expect(page).toHaveURL(/\/agent\?run=run-i18n&factor=factor-i18n&experiment=exp-i18n/);
  await expect(page.getByTestId("workbench-context-bar")).toContainText("factor-i18n");
  await expect.poll(() => page.evaluate((key) => localStorage.getItem(key), LOCALE_KEY)).toBe("zh-CN");

  await chinese.focus();
  const focusStyle = await chinese.evaluate((element) => {
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
