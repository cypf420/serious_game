import { defineConfig } from "@playwright/test";
import { tmpdir } from "node:os";
import path from "node:path";

const componentEvidenceDir = process.env.FULL_ACCEPTANCE_COMPONENT_DIR
  ? path.resolve(process.env.FULL_ACCEPTANCE_COMPONENT_DIR)
  : path.join(tmpdir(), "qingjiang-playwright-component");
const componentPort = Number(process.env.COMPONENT_WEB_PORT || 3101);

export default defineConfig({
  testDir: "./e2e",
  testMatch: ["component-game-shell.spec.ts", "tutorial.spec.ts", "action-semantics.spec.ts", "punctuation.spec.ts", "archive-history.spec.ts", "retired-overtime.spec.ts", "budget-sync.spec.ts", "contract-tutorial.spec.ts", "ending.spec.ts", "final-check.spec.ts"],
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: "line",
  outputDir: path.join(componentEvidenceDir, "artifacts"),
  use: {
    baseURL: `http://127.0.0.1:${componentPort}`,
    trace: "retain-on-failure",
  },
  webServer: {
    command: `npm run dev -- --port ${componentPort}`,
    url: `http://127.0.0.1:${componentPort}`,
    reuseExistingServer: false,
    timeout: 120_000,
  },
});
