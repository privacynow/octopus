module.exports = {
  testDir: '.',
  workers: 1,
  timeout: 30000,
  expect: { timeout: 5000 },
  reporter: 'list',
  use: {
    baseURL: 'http://127.0.0.1:8787',
    viewport: { width: 1360, height: 900 },
    screenshot: 'only-on-failure',
    video: 'off',
    trace: 'off',
  },
};
