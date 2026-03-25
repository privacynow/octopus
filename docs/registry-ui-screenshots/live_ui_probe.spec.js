const { test, expect } = require("@playwright/test");

function requireEnv(name) {
  const value = process.env[name] || "";
  if (!value) {
    throw new Error(`Missing required env: ${name}`);
  }
  return value;
}

const UI_TOKEN = requireEnv("UI_TOKEN");
const TARGET_URL = requireEnv("TARGET_URL");
const OBSERVE_MS = Number(process.env.OBSERVE_MS || "12000");

test("live ui probe", async ({ page }) => {
  test.setTimeout(Math.max(30000, OBSERVE_MS + 15000));

  await page.addInitScript(() => {
    const state = {
      fetches: [],
      ws: [],
      mutations: 0,
      href: "",
    };
    window.__probeState = state;

    const origFetch = window.fetch.bind(window);
    window.fetch = async (...args) => {
      const input = args[0];
      const url = typeof input === "string" ? input : (input && input.url) || "";
      state.fetches.push({ ts: Date.now(), url });
      return origFetch(...args);
    };

    const OrigWebSocket = window.WebSocket;
    window.WebSocket = function(...args) {
      const ws = new OrigWebSocket(...args);
      ws.addEventListener("message", (evt) => {
        try {
          const msg = JSON.parse(evt.data);
          state.ws.push({
            ts: Date.now(),
            type: msg.type || "",
            topic: (msg.data && msg.data.topic) || "",
            reason: (msg.data && msg.data.reason) || "",
            agent_id: (msg.data && msg.data.agent_id) || "",
            conversation_id: (msg.data && msg.data.conversation_id) || "",
          });
        } catch {
          state.ws.push({ ts: Date.now(), type: "raw" });
        }
      });
      return ws;
    };
    window.WebSocket.prototype = OrigWebSocket.prototype;
    Object.setPrototypeOf(window.WebSocket, OrigWebSocket);

    document.addEventListener("DOMContentLoaded", () => {
      const target = document.querySelector("main") || document.body;
      const observer = new MutationObserver((records) => {
        state.mutations += records.length;
        state.href = window.location.href;
      });
      observer.observe(target, { subtree: true, childList: true, characterData: true, attributes: true });
    });
  });

  await page.goto("/ui/login");
  await page.getByLabel(/password/i).fill(UI_TOKEN);
  await page.getByRole("button", { name: /sign in/i }).click();
  await expect(page).toHaveURL(/\/ui\/?$/);

  await page.goto(TARGET_URL);
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(OBSERVE_MS);

  const data = await page.evaluate(() => window.__probeState);
  console.log(JSON.stringify({
    targetUrl: TARGET_URL,
    observeMs: OBSERVE_MS,
    fetchCount: data.fetches.length,
    fetches: data.fetches.slice(-30),
    wsCount: data.ws.length,
    ws: data.ws.slice(-60),
    mutations: data.mutations,
    href: data.href,
  }, null, 2));
});
