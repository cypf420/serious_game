import {defineConfig} from '@playwright/test';
export default defineConfig({testDir:'./e2e',testMatch:['review-followup.spec.ts','review32.spec.ts','review28.spec.ts'],workers:1,retries:0,reporter:[['line'],['json',{outputFile:process.env.REVIEW_OUTPUT+'/results.json'}]],outputDir:process.env.REVIEW_OUTPUT,use:{baseURL:'http://127.0.0.1:3107',trace:'retain-on-failure'}});
