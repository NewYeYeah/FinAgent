import { defineConfig, devices } from "@playwright/test";

const external = Boolean(process.env.FINAGENT_R4_CONSOLE_URL);
process.env.FINAGENT_R4_CONSOLE_URL ??= "http://127.0.0.1:8765";
export default defineConfig({
  testDir: "./e2e",
  testMatch: "research-controller.spec.ts",
  fullyParallel: false,
  retries: 0,
  reporter: "line",
  use: { ...devices["Desktop Chrome"], trace: "retain-on-failure" },
  webServer: {
    command: "uv run --frozen python -m scripts.r4_console_fixture --output .finagent/r4-console-ci --serve",
    cwd: "..",
    url: `${process.env.FINAGENT_R4_CONSOLE_URL}/api/v3/streams/status`,
    timeout: 180000,
    reuseExistingServer: external,
  },
});
