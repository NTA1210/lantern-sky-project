const { defineConfig, devices } = require('@playwright/test');
const fs = require('node:fs');
const path = require('node:path');

const python = process.platform === 'win32'
  ? (fs.existsSync(path.join('.venv', 'Scripts', 'python.exe')) ? '.venv\\Scripts\\python.exe' : 'python')
  : (fs.existsSync(path.join('.venv', 'bin', 'python')) ? '.venv/bin/python' : 'python3');
const browserName = process.env.PLAYWRIGHT_BROWSER === 'firefox' ? 'firefox' : 'chromium';
const desktopDevice = browserName === 'firefox' ? devices['Desktop Firefox'] : devices['Desktop Chrome'];

module.exports = defineConfig({
  testDir: './tests/e2e',
  timeout: 30_000,
  expect: { timeout: 5_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [['list'], ['html', { outputFolder: 'playwright-report', open: 'never' }]],
  use: {
    baseURL: 'http://127.0.0.1:8765',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    viewport: { width: 1600, height: 900 },
  },
  projects: [
    {
      name: browserName,
      use: { ...desktopDevice },
    },
  ],
  webServer: {
    command: `${python} run.py`,
    url: 'http://127.0.0.1:8765/display',
    reuseExistingServer: false,
    timeout: 30_000,
    env: {
      ...process.env,
      PORT: '8765',
      LANTERN_NO_BROWSER: '1',
      LANTERN_DISABLE_CAMERA: '1',
      LANTERN_RUNTIME_DIR: 'runtime/e2e',
    },
  },
});
