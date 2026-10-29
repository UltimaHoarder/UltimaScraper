import { defineConfig } from '@playwright/test';
import base from './playwright.config';

// Captures the README and docs screenshots from the smoke mocks, so they never
// show a real account, creator or path: npm run screenshots
export default defineConfig({
  ...base,
  testDir: './tests/screenshots',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  projects: [
    {
      name: 'screenshots',
      use: {
        viewport: { width: 1440, height: 900 },
        colorScheme: 'dark',
        // The statistics charts draw with WebGL; headless Chromium needs SwiftShader.
        launchOptions: {
          ...base.use?.launchOptions,
          args: ['--no-sandbox', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
        },
      },
    },
  ],
});
