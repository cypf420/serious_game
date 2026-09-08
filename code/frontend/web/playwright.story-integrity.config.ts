import { defineConfig } from '@playwright/test';
import path from 'node:path';

export default defineConfig({
  testDir: './e2e', testMatch: 'story-integrity.spec.ts', workers: 1, retries: 0,
  timeout: 60_000, reporter: 'line',
  outputDir: path.resolve('../../../output/story-integrity/20260908-implementation/browser'),
  use: { baseURL: 'http://127.0.0.1:3103', trace: 'retain-on-failure', screenshot: 'only-on-failure' },
  webServer: { command: 'npm run dev -- --port 3103', url: 'http://127.0.0.1:3103', reuseExistingServer: false, timeout: 120_000 },
});
