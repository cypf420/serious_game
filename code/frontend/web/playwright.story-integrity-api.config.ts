import {defineConfig} from '@playwright/test';
import path from 'node:path';
export default defineConfig({
  testDir:'./e2e',testMatch:'story-integrity-api.spec.ts',workers:1,retries:0,timeout:90_000,reporter:'line',
  outputDir:path.resolve('../../../output/story-integrity/20260908-implementation/real-api-browser'),
  use:{baseURL:'http://127.0.0.1:3105',trace:'retain-on-failure',screenshot:'only-on-failure'},
  webServer:{command:'npm run start',env:{PORT:'3105',HOSTNAME:'127.0.0.1',GAME_BACKEND_URL:'http://127.0.0.1:8107'},url:'http://127.0.0.1:3105',reuseExistingServer:false,timeout:120_000},
});
