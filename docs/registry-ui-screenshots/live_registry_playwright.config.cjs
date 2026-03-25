const path = require("path");

module.exports = {
  testDir: __dirname,
  timeout: 30000,
  expect: { timeout: 5000 },
  workers: 1,
  reporter: "list",
  outputDir: process.env.E2E_PLAYWRIGHT_OUTPUT_DIR
    || path.join(__dirname, "..", "..", ".tmp", "e2e-live-smoke", "playwright-output"),
  use: {
    baseURL: process.env.E2E_BASE_URL || "http://127.0.0.1:8787",
    viewport: { width: 1360, height: 900 },
    screenshot: "only-on-failure",
    video: "off",
    trace: "off",
  },
};
