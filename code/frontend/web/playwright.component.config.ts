import { defineConfig } from "@playwright/test";
import { tmpdir } from "node:os";
import path from "node:path";

const componentEvidenceDir = process.env.FULL_ACCEPTANCE_COMPONENT_DIR
  ? path.resolve(process.env.FULL_ACCEPTANCE_COMPONENT_DIR)
  : path.join(tmpdir(), "qingjiang-playwright-component");

export default defineConfig({
  testDir: "./e2e",
  testMatch: ["component-game-shell.spec.ts", "tutorial.spec.ts"],
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: "line",
  outputDir: path.join(componentEvidenceDir, "artifacts"),
  use: {
    baseURL: "http://127.0.0.1:3101",
    trace: "retain-on-failure",
  },
  webServer: {
    command: "npm run dev -- --port 3101",
    url: "http://127.0.0.1:3101",
    reuseExistingServer: false,
    timeout: 120_000,
  },
});
