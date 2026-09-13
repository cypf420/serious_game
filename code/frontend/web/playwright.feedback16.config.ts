import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  testMatch: process.env.FEEDBACK16_REGRESSION ? ["component-game-shell.spec.ts", "tutorial.spec.ts", "budget-sync.spec.ts", "contract-tutorial.spec.ts"] : "feedback16.spec.ts",
  workers: 1,
  retries: 0,
  reporter: [["line"], ["json", { outputFile: `${process.env.FEEDBACK16_OUTPUT || "test-results/feedback16"}/results.json` }]],
  outputDir: process.env.FEEDBACK16_OUTPUT || "test-results/feedback16",
  use: { baseURL: process.env.FEEDBACK16_URL || "http://127.0.0.1:3107", trace: "retain-on-failure" },
});
