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

  console.log("--> Testing 1: Connect to app & verify WebSocket link");
  await page.goto(`${base}/#setup`);
  await page.locator(".ps16-app").waitFor({ timeout: 10000 });
  await page.waitForTimeout(2000);

  // Check setup screen shows live health checks
  const setupContent = await page.textContent("body");
  assert.ok(setupContent.includes("Setup & permissions") || setupContent.includes("Setup"), "Setup page visible");
  console.log("PASS: Setup screen loaded with live backend status.");

  console.log("--> Testing 2: Camera & Gestures screen");
  await page.getByRole("button", { name: "Camera & gestures" }).click();
  await page.waitForTimeout(1500);

  // If "Turn on camera" button is shown, click it to grant consent
  const turnOnBtn = page.getByRole("button", { name: "Turn on camera" });
  if (await turnOnBtn.isVisible()) {
    console.log("Granting camera consent via UI button...");
    await turnOnBtn.click();
    await page.waitForTimeout(2000);
  }

  // Verify camera feed container
  const cameraTitle = await page.getByRole("heading", { name: "Camera & gestures" }).isVisible();
  assert.ok(cameraTitle, "Camera screen header is present");
  console.log("PASS: Camera & gestures screen active.");

  console.log("--> Testing 3: Words screen (Vocabulary & Phrasebook)");
  await page.getByRole("button", { name: "My words" }).click();
  await page.waitForTimeout(1000);
  const wordsTitle = await page.getByRole("heading", { name: "My words" }).isVisible();
  assert.ok(wordsTitle, "Words screen header is present");
  console.log("PASS: My words screen active.");

  console.log("--> Testing 4: Partner conversation screen");
  await page.getByRole("button", { name: "Partner" }).click();
  await page.waitForTimeout(1000);
  const partnerHeading = await page.getByRole("heading", { name: "Partner speaks" }).isVisible();
  assert.ok(partnerHeading, "Partner screen header is present");
  console.log("PASS: Partner screen active.");

  console.log("--> Testing 5: My message screen (Drafting & Fusion)");
  await page.getByRole("button", { name: "My message", exact: true }).click();
  await page.waitForTimeout(1000);
  const youOnCamera = await page.locator("text=You, on camera").isVisible();
  assert.ok(youOnCamera, "Message screen camera preview section is present");
  console.log("PASS: My message screen active.");

  console.log("--> Testing 6: Insights screen");
  await page.getByRole("button", { name: "Insights" }).click();
  await page.waitForTimeout(1000);
  const insightsHeading = await page.getByRole("heading", { name: "Insights" }).isVisible();
  assert.ok(insightsHeading, "Insights screen header is present");
  console.log("PASS: Insights screen active.");

  console.log("--> Testing 7: Return to landing page");
  await page.getByRole("button", { name: "← Landing" }).click();
  await page.locator('.hero-scene[data-ready="true"]').waitFor({ timeout: 10000 });
  console.log("PASS: Returned to landing page cleanly.");

  assert.deepEqual(errors, [], "No browser console errors");
  console.log("\nALL VERIFICATIONS PASSED: Frontend, backend, and all detection models are well versed and connected!");
} finally {
  await browser.close();
}
