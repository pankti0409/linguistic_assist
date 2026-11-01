import { chromium } from "@playwright/test";
import assert from "node:assert/strict";

const base = process.env.TEST_URL || "http://127.0.0.1:5173";
const browser = await chromium.launch({
  channel: process.env.PLAYWRIGHT_CHANNEL || "chrome",
  headless: true,
});

try {
  const page = await browser.newPage({
    viewport: { width: 1440, height: 900 },
  });
  const errors = [];
  page.on("pageerror", (err) => errors.push(err.message));

  console.log("1. Navigating to landing page...");
  await page.goto(base);
  await page.locator('.hero-scene[data-ready="true"]').waitFor({ timeout: 15000 });
  console.log("Landing page loaded successfully.");

  console.log("2. Clicking 'Open Sampark' to open the app in-place...");
  await page.getByRole("link", { name: "Open Sampark" }).first().click();
  await page.waitForTimeout(500);

  // Check URL hash is #message
  assert.equal(new URL(page.url()).hash, "#message");
  
  // Verify PS16 app container is present
  await page.locator(".ps16-app").waitFor({ timeout: 5000 });
  console.log("PS16App mounted with active screen: message.");

  // Check navigation tabs inside the app
  const screens = [
    { name: "Partner", hash: "#partner" },
    { name: "Camera & gestures", hash: "#camera" },
    { name: "My words", hash: "#words" },
    { name: "Setup & permissions", hash: "#setup" },
    { name: "Insights", hash: "#insights" },
    { name: "My message", hash: "#message" }
  ];

  for (const s of screens) {
    console.log(`Switching to screen: ${s.name}`);
    await page.getByRole("button", { name: s.name, exact: true }).click();
    await page.waitForTimeout(300);
    assert.equal(new URL(page.url()).hash, s.hash);
  }

  // Click "← Landing" button
  console.log("3. Testing return to landing page...");
  await page.getByRole("button", { name: "← Landing" }).click();
  await page.waitForTimeout(500);

  // Check landing page is active again
  assert.equal(await page.locator('.hero-scene[data-ready="true"]').isVisible(), true);
  console.log("Returned to landing page successfully.");

  assert.deepEqual(errors, [], "No console errors detected");
  console.log("PASS: In-app integration verified completely!");
} finally {
  await browser.close();
}
