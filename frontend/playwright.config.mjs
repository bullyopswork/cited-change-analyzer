import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  testMatch: '**/*.pw.mjs',
  timeout: 30_000,
  fullyParallel: false,
  workers: 1,
  reporter: [['list'], ['json', { outputFile: '../.local/qa/results.json' }]],
  outputDir: '../.local/qa/test-results',
  use: {
    baseURL: process.env.CCA_BASE_URL || 'http://127.0.0.1:8791',
    viewport: { width: 1440, height: 1000 },
    launchOptions: process.env.CCA_BROWSER_EXECUTABLE ? { executablePath: process.env.CCA_BROWSER_EXECUTABLE } : {},
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  webServer: process.env.CCA_BASE_URL ? undefined : {
    command: 'npm run preview -- --host 127.0.0.1 --port 8791',
    url: 'http://127.0.0.1:8791',
    reuseExistingServer: !process.env.CI,
  },
});
