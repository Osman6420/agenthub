import { defineConfig } from "@playwright/test";
import { existsSync } from "node:fs";
import { resolve } from "node:path";

const workspace = resolve(process.cwd(), "..");
const windowsPython = resolve(workspace, ".venv", "Scripts", "python.exe");
const python = existsSync(windowsPython) ? `"${windowsPython}"` : "python";
const configuredBrowser = process.env.BROWSER_GATE_BROWSER_PATH;
const localEdge = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const executablePath = configuredBrowser ||
  (process.platform === "win32" && existsSync(localEdge) ? localEdge : undefined);

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  timeout: 30_000,
  expect: { timeout: 8_000 },
  reporter: "line",
  outputDir: "../.tmp/playwright-results",
  use: {
    baseURL: "http://127.0.0.1:8011",
    browserName: "chromium",
    headless: true,
    screenshot: "only-on-failure",
    trace: "off",
    video: "off",
    launchOptions: executablePath ? { executablePath } : undefined,
  },
  webServer: {
    command: `${python} ../scripts/run_phase_2_9_browser_gate.py`,
    url: "http://127.0.0.1:8011/v1/health/live",
    reuseExistingServer: false,
    timeout: 120_000,
    env: {
      ...process.env,
      BROWSER_GATE_FIXTURE_PATH: resolve(workspace, ".tmp", "phase-2-9-browser-fixture.json"),
    },
  },
});
