const { defineConfig } = require("@playwright/test");

/** Screenshots for docs/manual fixtures (static HTML, no registry server). */
module.exports = defineConfig({
  workers: 1,
  testDir: ".",
  testMatch: "capture-manual.spec.ts",
  timeout: 120000,
  expect: { timeout: 10000 },
  use: {
    viewport: { width: 1280, height: 900 },
    screenshot: "only-on-failure",
    video: "off",
  },
});
