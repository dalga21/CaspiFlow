import {defineConfig,devices} from '@playwright/test';
const baseURL=process.env.CASPIFLOW_PUBLIC_URL;
if(!baseURL?.startsWith('https://'))throw new Error('Set CASPIFLOW_PUBLIC_URL to the actual public HTTPS origin');
export default defineConfig({
 testDir:'./tests/public',workers:1,fullyParallel:false,timeout:90000,
 expect:{timeout:20000},outputDir:'../.runtime/public-playwright-results',
 reporter:[['list'],['html',{outputFolder:'../.runtime/public-playwright-report',open:'never'}]],
 use:{baseURL,trace:'off',screenshot:'only-on-failure'},
 projects:[
  {name:'desktop',use:{...devices['Desktop Chrome'],viewport:{width:1440,height:1000}}},
  {name:'mobile',use:{...devices['iPhone 13'],defaultBrowserType:'chromium'}},
 ],
});
