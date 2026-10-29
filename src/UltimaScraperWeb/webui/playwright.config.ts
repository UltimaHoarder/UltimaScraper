import fs from 'node:fs';
import path from 'node:path';
import { defineConfig, devices } from '@playwright/test';

const localBrowserPath = [
  process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE,
  '/usr/bin/chromium',
  '/usr/bin/google-chrome-stable',
].find((candidate) => candidate && fs.existsSync(candidate));

// The page is served as through the WebUI server; every backend and sign-in
// request is answered in the browser, so the server address is a closed port.
const webServerCommand =
  'USR_WEBUI_SERVER_URL=http://127.0.0.1:9 npm run dev -- --host 127.0.0.1 --port 4173';

export default defineConfig({
  testDir: './tests/smoke',
  fullyParallel: true,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 4 : 4,
  projects: [
    {
      name: 'desktop',
      use: {
        viewport: { width: 1440, height: 960 },
      },
    },
    {
      name: 'tablet',
      use: {
        viewport: { width: 1024, height: 1366 },
        deviceScaleFactor: 2,
        hasTouch: true,
        isMobile: false,
      },
    },
    {
      name: 'mobile',
      use: {
        ...devices['Pixel 7'],
      },
    },
  ],
  use: {
    baseURL: 'http://127.0.0.1:4173',
    headless: true,
    trace: 'retain-on-failure',
    launchOptions: localBrowserPath
      ? {
          executablePath: path.resolve(localBrowserPath),
          args: ['--no-sandbox'],
        }
      : {
          args: ['--no-sandbox'],
        },
  },
  webServer: {
    command: webServerCommand,
    url: 'http://127.0.0.1:4173',
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
