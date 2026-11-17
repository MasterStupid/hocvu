import { existsSync } from 'node:fs';
import { defineConfig, devices } from '@playwright/test';

// Use Replit's system Chromium if present; elsewhere use Playwright's installed browser.
const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH
  || (existsSync('/repl/tools/bin/chromium') ? '/repl/tools/bin/chromium' : undefined);

export default defineConfig({
  testDir: './tests/browser',
  testMatch: '**/*.spec.ts',
  fullyParallel: true,
  workers: 2,
  retries: 0,
  timeout: 30_000,
  expect: { timeout: 5_000 },
  outputDir: '../../generated-artifacts/hocvu-browser/results',
  reporter: [
    ['list'],
    ['html', { outputFolder: '../../generated-artifacts/hocvu-browser/report', open: 'never' }],
  ],
  use: {
    baseURL: 'http://127.0.0.1:4179',
    serviceWorkers: 'block',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [{
    name: 'chromium',
    use: { ...devices['Desktop Chrome'], launchOptions: { executablePath } },
  }],
  webServer: {
    command: 'pnpm exec vite --config vite.browser.config.ts',
    url: 'http://127.0.0.1:4179/documents',
    reuseExistingServer: false,
    timeout: 30_000,
  },
});
