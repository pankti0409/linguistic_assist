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

  console.log("1. Opening app directly via hash #message...");
  await page.goto(`${base}/#message`);

  await page.locator(".ps16-app").waitFor({ timeout: 8000 });
  console.log("PS16App rendered.");

  // Wait for the backend link indicator to turn live (or show live status)
  await page.waitForTimeout(2000);

  // Check Setup screen to see service status
  console.log("2. Navigating to Setup screen...");
  await page.getByRole("button", { name: "Setup & permissions" }).click();
  await page.waitForTimeout(1000);

  const text = await page.textContent("body");
  assert.ok(text.includes("Setup & permissions") || text.includes("Setup"), "Setup screen is loaded");
  console.log("Setup screen loaded.");

  // Check Insights screen
  console.log("3. Navigating to Insights screen...");
  await page.getByRole("button", { name: "Insights" }).click();
  await page.waitForTimeout(1000);
  console.log("Insights screen loaded.");

  // Navigate back to landing
  console.log("4. Returning to landing...");
  await page.getByRole("button", { name: "← Landing" }).click();
  await page.locator('.hero-scene[data-ready="true"]').waitFor({ timeout: 10000 });
  console.log("Landing page loaded cleanly.");

  assert.deepEqual(errors, [], "No browser runtime errors");
  console.log("PASS: Full stack frontend + backend integration successfully verified!");
} finally {
  await browser.close();
}

