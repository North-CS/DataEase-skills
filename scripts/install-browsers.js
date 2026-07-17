#!/usr/bin/env node
"use strict";

// Graceful browser installation for DataEase Skill
// Chromium is required for dashboard/DataV screenshots, but the CLI
// and all other features work without it.

const { execSync } = require("child_process");
const fs = require("fs");
const path = require("path");

const BROWSER_CACHE_KEY = path.join(__dirname, "..", ".browsers-installed");
const SKIP_FLAG = process.env.DATAEASE_SKIP_BROWSER_INSTALL;

if (SKIP_FLAG === "1" || SKIP_FLAG === "true") {
  console.log("DATAEASE_SKIP_BROWSER_INSTALL set — skipping Playwright browser install.");
  process.exit(0);
}

if (fs.existsSync(BROWSER_CACHE_KEY)) {
  console.log("Playwright browsers already installed (marker found).");
  process.exit(0);
}

try {
  console.log("Installing Playwright Chromium for dashboard/DataV screenshots...");
  execSync("npx playwright install chromium", {
    stdio: "inherit",
    timeout: 180_000, // 3 minutes — generous for slow networks
  });
  fs.writeFileSync(BROWSER_CACHE_KEY, new Date().toISOString(), "utf-8");
  console.log("Chromium installed successfully.");
} catch (err) {
  console.error(
    "WARNING: Playwright Chromium install failed. " +
    "Screenshots will be unavailable, but all other features work normally.\n" +
    "To retry later: npx playwright install chromium\n" +
    "To suppress this warning: set DATAEASE_SKIP_BROWSER_INSTALL=1"
  );
  // Do not fail the install — exit 0 so npm continues
  process.exit(0);
}
