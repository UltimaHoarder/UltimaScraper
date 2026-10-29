import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    setupFiles: ['./tests/unit/setup.ts'],
    include: ['tests/unit/**/*.test.ts', 'tests/unit/**/*.test.tsx'],
    css: false,
    // Full-workspace interaction tests take 3-5s on parallel workers; the 5s
    // default made them fail intermittently without any assertion failing.
    testTimeout: 15_000,
    restoreMocks: true,
    clearMocks: true,
    mockReset: true,
  },
});
