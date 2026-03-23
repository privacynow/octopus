/**
 * Optional: captures static HTML fixtures to docs/assets/manual/*.png + *.meta.json
 * for annotate.py. The user manual uses SVGs; keep this for regression or extra raster assets.
 */
import { test, expect } from "@playwright/test";
import * as fs from "fs";
import * as path from "path";
import { pathToFileURL } from "url";

const FIX = path.join(__dirname, "fixtures", "manual");
const OUT = path.join(__dirname, "..", "assets", "manual");

async function absRect(page: import("@playwright/test").Page, selector: string) {
  const n = await page.locator(selector).first().count();
  if (n === 0) return null;
  return page.locator(selector).first().evaluate((el) => {
    const r = el.getBoundingClientRect();
    return { x: r.left + window.scrollX, y: r.top + window.scrollY, width: r.width, height: r.height };
  });
}

async function writeOverlayMeta(
  page: import("@playwright/test").Page,
  pngPath: string,
  rects: Array<{ selector: string; label: string; color?: string; pad?: number }>,
  arrows: Array<{ fromSel: string; toSel: string }> = [],
) {
  const metaPath = pngPath.replace(/\.png$/i, ".meta.json");
  const outRects: Array<{
    x: number;
    y: number;
    width: number;
    height: number;
    label?: string;
    color?: string;
  }> = [];
  for (const r of rects) {
    const box = await absRect(page, r.selector);
    if (!box) continue;
    const pad = r.pad ?? 6;
    outRects.push({
      x: Math.max(0, box.x - pad),
      y: Math.max(0, box.y - pad),
      width: box.width + 2 * pad,
      height: box.height + 2 * pad,
      label: r.label,
      color: r.color ?? "#ff9800",
    });
  }
  const arrowPixels: Array<{ x1: number; y1: number; x2: number; y2: number }> = [];
  for (const a of arrows) {
    const ra = await absRect(page, a.fromSel);
    const rb = await absRect(page, a.toSel);
    if (!ra || !rb) continue;
    const x1 = ra.x + ra.width / 2;
    const y1 = ra.y + ra.height;
    const x2 = rb.x + rb.width / 2;
    const y2 = rb.y;
    arrowPixels.push({ x1, y1, x2, y2 });
  }
  await fs.promises.writeFile(metaPath, JSON.stringify({ rects: outRects, arrows: arrowPixels }, null, 2), "utf-8");
}

function fixture(name: string): string {
  return pathToFileURL(path.join(FIX, name)).href;
}

test.beforeAll(() => {
  fs.mkdirSync(OUT, { recursive: true });
});

test("capture manual fixtures for operator & product docs", async ({ page }) => {
  // --- Setup (illustrative mocks) ---
  await page.goto(fixture("setup-01-botfather.html"));
  await page.waitForSelector('[data-doc="token"]');
  await page.screenshot({ path: path.join(OUT, "setup-01-botfather.png"), fullPage: true });
  await writeOverlayMeta(page, path.join(OUT, "setup-01-botfather.png"), [
    { selector: '[data-doc="bf"]', label: "@BotFather /newbot flow", color: "#2196f3", pad: 8 },
    { selector: '[data-doc="token"]', label: "Copy token into Octopus", color: "#ff9800", pad: 8 },
  ]);

  await page.goto(fixture("setup-02-provider-auth.html"));
  await page.screenshot({ path: path.join(OUT, "setup-02-provider-auth.png"), fullPage: true });
  await writeOverlayMeta(page, path.join(OUT, "setup-02-provider-auth.png"), [
    { selector: '[data-doc="title"]', label: "Claude or Codex sign-in", color: "#e94560", pad: 8 },
    { selector: '[data-doc="hint"]', label: "Verify with ./octopus status", color: "#7ec8e3", pad: 6 },
  ]);

  await page.goto(fixture("setup-03-first-bot-wizard.html"));
  await page.screenshot({ path: path.join(OUT, "setup-03-first-bot-wizard.png"), fullPage: true });
  await writeOverlayMeta(page, path.join(OUT, "setup-03-first-bot-wizard.png"), [
    { selector: '[data-doc="token"]', label: "Token from BotFather", color: "#ff9800", pad: 6 },
    { selector: '[data-doc="prov"]', label: "Claude or Codex", color: "#2196f3", pad: 6 },
    { selector: '[data-doc="mode"]', label: "Safe / autonomous / advanced", color: "#4caf50", pad: 6 },
    { selector: '[data-doc="doc"]', label: "Doctor then start", color: "#9c27b0", pad: 6 },
  ]);

  // --- Octopus (terminal mock) ---
  await page.goto(fixture("oct-01-main-menu.html"));
  await page.waitForSelector("[data-doc=menu]");
  await page.screenshot({ path: path.join(OUT, "oct-01-main-menu.png"), fullPage: true });
  await writeOverlayMeta(page, path.join(OUT, "oct-01-main-menu.png"), [
    { selector: '[data-doc="title"]', label: "Primary entry when bots exist", color: "#2196f3", pad: 8 },
    { selector: '[data-doc="menu"]', label: "Add bot · Manage · Registry · Workspace · Advanced", color: "#ff9800", pad: 8 },
  ]);

  await page.goto(fixture("oct-02-manage-bot.html"));
  await page.screenshot({ path: path.join(OUT, "oct-02-manage-bot.png"), fullPage: true });
  await writeOverlayMeta(page, path.join(OUT, "oct-02-manage-bot.png"), [
    { selector: '[data-doc="menu"]', label: "Logs · restart · doctor · settings · registry", color: "#ff9800", pad: 8 },
  ]);

  await page.goto(fixture("oct-03-edit-settings.html"));
  await page.screenshot({ path: path.join(OUT, "oct-03-edit-settings.png"), fullPage: true });
  await writeOverlayMeta(page, path.join(OUT, "oct-03-edit-settings.png"), [
    { selector: '[data-doc="summary"]', label: "Current display name, provider, mode", color: "#2196f3", pad: 6 },
    { selector: '[data-doc="menu"]', label: "Name, role, tags, access, timeout, editor", color: "#ff9800", pad: 6 },
  ]);

  await page.goto(fixture("oct-04-status.html"));
  await page.screenshot({ path: path.join(OUT, "oct-04-status.png"), fullPage: true });
  await writeOverlayMeta(page, path.join(OUT, "oct-04-status.png"), [
    { selector: '[data-doc="bots"]', label: "Per-bot provider, mode, running state", color: "#2196f3", pad: 6 },
    { selector: '[data-doc="registry"]', label: "Local registry up/down + UI URL", color: "#4caf50", pad: 6 },
    { selector: '[data-doc="auth"]', label: "Claude / Codex login state", color: "#9c27b0", pad: 6 },
  ]);

  await page.goto(fixture("oct-05-registry-menu.html"));
  await page.screenshot({ path: path.join(OUT, "oct-05-registry-menu.png"), fullPage: true });
  await writeOverlayMeta(page, path.join(OUT, "oct-05-registry-menu.png"), [
    { selector: '[data-doc="menu"]', label: "start · stop · logs · status · connect", color: "#ff9800", pad: 8 },
  ]);

  await page.goto(fixture("oct-06-remote-registry.html"));
  await page.screenshot({ path: path.join(OUT, "oct-06-remote-registry.png"), fullPage: true });
  await writeOverlayMeta(page, path.join(OUT, "oct-06-remote-registry.png"), [
    { selector: '[data-doc="url"]', label: "HTTPS registry base URL", color: "#2196f3", pad: 6 },
    { selector: '[data-doc="token"]', label: "Enrollment token from operator", color: "#ff9800", pad: 6 },
    { selector: '[data-doc="scope"]', label: "full · channel · coordination", color: "#4caf50", pad: 6 },
  ]);

  await page.goto(fixture("oct-07-workspace.html"));
  await page.screenshot({ path: path.join(OUT, "oct-07-workspace.png"), fullPage: true });
  await writeOverlayMeta(page, path.join(OUT, "oct-07-workspace.png"), [
    { selector: '[data-doc="help"]', label: "create · add-bot · verify host paths", color: "#ff9800", pad: 8 },
  ]);

  await page.goto(fixture("oct-08-advanced.html"));
  await page.screenshot({ path: path.join(OUT, "oct-08-advanced.png"), fullPage: true });
  await writeOverlayMeta(page, path.join(OUT, "oct-08-advanced.png"), [
    { selector: '[data-doc="menu"]', label: "Full add-bot wizard · webhook mode", color: "#ff9800", pad: 8 },
  ]);

  await page.goto(fixture("oct-09-webhook.html"));
  await page.screenshot({ path: path.join(OUT, "oct-09-webhook.png"), fullPage: true });
  await writeOverlayMeta(page, path.join(OUT, "oct-09-webhook.png"), [
    { selector: '[data-doc="url"]', label: "Public HTTPS webhook URL", color: "#2196f3", pad: 6 },
    { selector: '[data-doc="port"]', label: "Listen port inside container", color: "#ff9800", pad: 6 },
  ]);

  await page.goto(fixture("oct-10-clean.html"));
  await page.screenshot({ path: path.join(OUT, "oct-10-clean.png"), fullPage: true });
  await writeOverlayMeta(page, path.join(OUT, "oct-10-clean.png"), [
    { selector: '[data-doc="warn"]', label: "Destroys .deploy, volumes, provider auth", color: "#e53935", pad: 8 },
  ]);

  // --- Telegram (chat mock) ---
  await page.goto(fixture("tg-01-start-help.html"));
  await page.screenshot({ path: path.join(OUT, "tg-01-start-help.png"), fullPage: true });
  await writeOverlayMeta(page, path.join(OUT, "tg-01-start-help.png"), [
    { selector: '[data-doc="help"]', label: "/help lists commands + deep links", color: "#2196f3", pad: 8 },
    { selector: '[data-doc="bubble"]', label: "Normal messages go to the agent", color: "#4caf50", pad: 6 },
  ]);

  await page.goto(fixture("tg-02-settings.html"));
  await page.screenshot({ path: path.join(OUT, "tg-02-settings.png"), fullPage: true });
  await writeOverlayMeta(page, path.join(OUT, "tg-02-settings.png"), [
    { selector: '[data-doc="panel"]', label: "Inline buttons → setting_* callbacks", color: "#ff9800", pad: 8 },
  ]);

  await page.goto(fixture("tg-03-skills.html"));
  await page.screenshot({ path: path.join(OUT, "tg-03-skills.png"), fullPage: true });
  await writeOverlayMeta(page, path.join(OUT, "tg-03-skills.png"), [
    { selector: '[data-doc="list"]', label: "/skills list · add · setup", color: "#2196f3", pad: 8 },
  ]);

  await page.goto(fixture("tg-04-approval.html"));
  await page.screenshot({ path: path.join(OUT, "tg-04-approval.png"), fullPage: true });
  await writeOverlayMeta(page, path.join(OUT, "tg-04-approval.png"), [
    { selector: '[data-doc="gate"]', label: "/approval · /approve · /reject", color: "#ff9800", pad: 8 },
    { selector: '[data-doc="plan"]', label: "Plan preview before run (safe mode)", color: "#2196f3", pad: 6 },
  ]);

  await page.goto(fixture("tg-05-runtime-modes.html"));
  await page.screenshot({ path: path.join(OUT, "tg-05-runtime-modes.png"), fullPage: true });
  await writeOverlayMeta(page, path.join(OUT, "tg-05-runtime-modes.png"), [
    { selector: '[data-doc="standalone"]', label: "Dedicated process: full /commands incl. /guidance", color: "#4caf50", pad: 6 },
    { selector: '[data-doc="shared"]', label: "Shared worker: subset direct + routed commands", color: "#2196f3", pad: 6 },
  ]);

  // --- API map ---
  await page.goto(fixture("api-01-surface.html"));
  await page.screenshot({ path: path.join(OUT, "api-01-surface.png"), fullPage: true });
  await writeOverlayMeta(page, path.join(OUT, "api-01-surface.png"), [
    { selector: '[data-doc="agents"]', label: "Enroll · heartbeat · discovery", color: "#2196f3", pad: 6 },
    { selector: '[data-doc="conv"]', label: "Events · messages · export", color: "#4caf50", pad: 6 },
    { selector: '[data-doc="skills"]', label: "Catalog lifecycle (API-only ops)", color: "#9c27b0", pad: 6 },
    { selector: '[data-doc="guidance"]', label: "Provider guidance drafts (no UI nav)", color: "#ff9800", pad: 6 },
  ]);

  await page.goto(fixture("tr-01-symptoms.html"));
  await page.screenshot({ path: path.join(OUT, "tr-01-symptoms.png"), fullPage: true });
  await writeOverlayMeta(page, path.join(OUT, "tr-01-symptoms.png"), [
    { selector: '[data-doc="flow"]', label: "status → doctor → logs → registry", color: "#2196f3", pad: 8 },
  ]);

  expect(fs.existsSync(path.join(OUT, "tr-01-symptoms.png"))).toBeTruthy();
});
