import { chromium } from "@playwright/test";
import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";

const base = process.env.TEST_URL || "http://127.0.0.1:5173";
const browser = await chromium.launch({
  channel: process.env.PLAYWRIGHT_CHANNEL || "chrome",
  headless: true,
  args: [
    "--enable-webgl",
    "--use-angle=swiftshader",
    "--enable-unsafe-swiftshader",
  ],
});
const errors = [];
await mkdir("artifacts", { recursive: true });

async function makePage(options) {
  const page = await browser.newPage(options);
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("response", (response) => {
    if (response.status() >= 400)
      errors.push(`${response.status()} ${response.url()}`);
  });
  await page.goto(base);
  await page
    .locator('.hero-scene[data-ready="true"]')
    .waitFor({ timeout: 30000 });
  await page.evaluate(() => document.fonts.ready);
  return page;
}

try {
  const desktop = await makePage({
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 1,
  });
  await desktop.getByRole("button", { name: "Pause background scene" }).click();
  await desktop
    .getByRole("button", { name: "Play background scene" })
    .waitFor();
  await desktop.waitForTimeout(1600);
  await desktop.screenshot({ path: "artifacts/desktop-hero.png" });
  assert.equal(await desktop.locator("h1").textContent(), "SAMPARK");
  await desktop.getByRole("link", { name: "Our purpose", exact: true }).click();
  await desktop.waitForTimeout(700);
  assert.equal(new URL(desktop.url()).hash, "#purpose");
  await desktop.getByRole("button", { name: "A familiar feeling" }).click();
  await desktop.getByText('“I need to take a break.”', { exact: true }).waitFor();
  await desktop.getByRole("button", { name: "Next example" }).click();
  await desktop.getByText('“Please sit with me for a moment.”', { exact: true }).waitFor();
  await desktop.getByRole("tab", { name: "A simple gesture" }).click();
  await desktop.getByRole("tabpanel").getByText("Let your hands").waitFor();
  assert.match(
    await desktop.locator(".message-example").textContent(),
    /I want water/,
  );
  await desktop
    .getByRole("tab", { name: "A simple gesture" })
    .press("ArrowRight");
  assert.equal(
    await desktop
      .getByRole("tab", { name: "A shared moment" })
      .getAttribute("aria-selected"),
    "true",
  );
  await desktop.getByRole("tab", { name: "A few words" }).click();
  for (const id of ["purpose", "studio", "possibilities", "milestones", "how-it-works"]) {
    await desktop.locator(`#${id}`).scrollIntoViewIfNeeded();
    await desktop.waitForTimeout(950);
  }
  await desktop.locator(".closing").scrollIntoViewIfNeeded();
  await desktop.waitForTimeout(950);
  await desktop.screenshot({
    path: "artifacts/desktop-full.png",
    fullPage: true,
  });
  assert.equal(
    await desktop.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
    true,
    "Desktop must not overflow horizontally",
  );
  assert.equal(
    await desktop
      .getByRole("link", { name: "Find your expression" })
      .getAttribute("href"),
    "#message",
  );

  const mobile = await makePage({
    viewport: { width: 390, height: 844 },
    deviceScaleFactor: 1,
    isMobile: true,
    hasTouch: true,
  });
  await mobile.getByRole("button", { name: "Pause background scene" }).click();
  await mobile.waitForTimeout(1600);
  await mobile.screenshot({ path: "artifacts/mobile-hero.png" });
  await mobile.getByRole("button", { name: "Open navigation" }).click();
  await mobile
    .getByRole("navigation", { name: "Mobile navigation" })
    .getByRole("link", { name: "Ways to connect" })
    .click();
  assert.equal(await mobile.locator("#mobile-nav").count(), 0);
  await mobile.getByRole("tab", { name: "A shared moment" }).click();
  assert.match(
    await mobile.locator(".message-example").textContent(),
    /Water, please/,
  );
  assert.equal(
    await mobile.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
    true,
    "Mobile must not overflow horizontally",
  );
  for (const id of ["purpose", "studio", "possibilities", "milestones", "how-it-works"]) {
    await mobile.locator(`#${id}`).scrollIntoViewIfNeeded();
    await mobile.waitForTimeout(950);
  }
  await mobile.locator(".closing").scrollIntoViewIfNeeded();
  await mobile.waitForTimeout(950);
  await mobile.screenshot({
    path: "artifacts/mobile-full.png",
    fullPage: true,
  });

  const reduced = await makePage({
    viewport: { width: 1440, height: 900 },
    reducedMotion: "reduce",
  });
  await reduced
    .getByRole("button", { name: "Play background scene" })
    .waitFor();
  await reduced.screenshot({ path: "artifacts/reduced-motion.png" });
  await reduced.getByRole("button", { name: "Switch to dark mode" }).click();
  await reduced.locator('.hero-scene[data-ready="true"]').waitFor();
  assert.equal(await reduced.locator('html').getAttribute('data-theme'), 'dark');
  await reduced.screenshot({ path: "artifacts/dark-hero.png" });
  await reduced.reload();
  await reduced.locator('.hero-scene[data-ready="true"]').waitFor();
  assert.equal(await reduced.locator('html').getAttribute('data-theme'), 'dark');
  await reduced.getByRole("button", { name: "Switch to light mode" }).click();
  await reduced.locator('.hero-scene[data-ready="true"]').waitFor();
  await reduced.getByRole("button", { name: "Play background scene" }).click();
  await reduced
    .getByRole("button", { name: "Pause background scene" })
    .waitFor();

  const fallback = await browser.newPage({
    viewport: { width: 390, height: 844 },
    reducedMotion: "reduce",
  });
  await fallback.addInitScript(() => {
    const getContext = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function (name, ...args) {
      if (name === "webgl") return null;
      return getContext.call(this, name, ...args);
    };
  });
  await fallback.goto(base);
  await fallback.locator("h1.fallback-title").waitFor({ state: "visible" });
  assert.equal(await fallback.locator(".scene-fallback").isVisible(), true);
  assert.deepEqual(errors, [], "No browser errors or failed requests");
  console.log(
    "PASS: desktop/mobile layouts, video pause/play, reduced motion, WebGL fallback, navigation, expression tabs, keyboard controls, app links, and clean browser console.",
  );
  console.log("Screenshots saved to f_new/artifacts/.");
} finally {
  await browser.close();
}
