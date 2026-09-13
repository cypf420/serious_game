import { defineConfig } from "@playwright/test";
export default defineConfig({ testDir: './e2e', testMatch: 'feedback33.spec.ts', workers: 1,
  reporter: [['list'], ['json', {outputFile: 'E:/严肃游戏/output/feedback17-33-20260913/ui-results.json'}]],
  outputDir: 'E:/严肃游戏/output/feedback17-33-20260913/ui',
  use: {baseURL: 'http://127.0.0.1:3107', trace: 'retain-on-failure'} });
