const path = require("path");
const { defineConfig } = require("@playwright/test");

const repoRoot = path.resolve(__dirname, "..", "..");
const dbPath = path.join(__dirname, ".capture-registry.sqlite3");
const py = path.join(repoRoot, ".venv", "bin", "python");

// Tokens must not match _KNOWN_DEFAULT_TOKENS in app/channels/registry/auth.py
const enroll = "guide-capture-enroll-token-2026";
const ui = "guide-capture-ui-token-2026";

module.exports = defineConfig({
  workers: 1,
  testDir: ".",
  timeout: 180000,
  expect: { timeout: 15000 },
  use: {
    baseURL: "http://127.0.0.1:19987",
    viewport: { width: 1360, height: 860 },
    screenshot: "only-on-failure",
    video: "off",
  },
  webServer: {
    command: [
      `REGISTRY_DB_PATH=${dbPath}`,
      `REGISTRY_ENROLL_TOKEN=${enroll}`,
      `REGISTRY_UI_TOKEN=${ui}`,
      "REGISTRY_ALLOW_HTTP=1",
      `PYTHONPATH=${repoRoot}`,
      `${py} -m uvicorn app.channels.registry.http:app --host 127.0.0.1 --port 19987`,
    ].join(" "),
    cwd: repoRoot,
    url: "http://127.0.0.1:19987/healthz",
    reuseExistingServer: true,
    timeout: 120000,
    stdout: "pipe",
    stderr: "pipe",
  },
});
