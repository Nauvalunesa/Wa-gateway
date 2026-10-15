import {defineConfig} from '@playwright/test'
export default defineConfig({testDir:'./e2e',workers:1,timeout:30000,use:{baseURL:process.env.TEST_BASE_URL||'http://127.0.0.1:18880',viewport:{width:1440,height:1000},headless:true,launchOptions:{executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE,args:['--no-sandbox']}},reporter:'list'})
