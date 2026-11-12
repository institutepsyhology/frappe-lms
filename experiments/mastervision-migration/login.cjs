'use strict';

// Interactive one-time login only. This file does not start the collector.
const path = require('node:path');
const fs = require('node:fs');
const { ORIGIN, PROFILE } = require('./transport.cjs');
const CATALOG = ORIGIN + '/shop/training/admin/admin?lg=ru';

function loadPlaywright() {
  for (const name of ['playwright', '@playwright/test']) {
    try { return require(name); } catch (_) { /* Use the installed bundled runtime. */ }
  }
  const bundled = path.join(process.env.USERPROFILE || '',
    '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
  try { return require(bundled); } catch (_) { throw new Error('playwright_unavailable'); }
}

function isCatalog(url, status, html) {
  try {
    const actual = new URL(url);
    return actual.origin === ORIGIN && actual.pathname === '/shop/training/admin/admin' &&
      !actual.username && !actual.password && status === 200 && typeof html === 'string' &&
      /<[^>]+\bid\s*=\s*(["'])training-grid\1/i.test(html);
  } catch (_) { return false; }
}

async function run() {
  if (process.argv.length !== 2) throw new Error('invalid_argument');
  const playwright = loadPlaywright();
  fs.mkdirSync(PROFILE, { recursive: true });
  const browser = await playwright.chromium.launchPersistentContext(PROFILE, {
    channel: 'msedge', headless: false, chromiumSandbox: true,
  });
  let verified = false;
  try {
    const page = browser.pages()[0] || await browser.newPage();
    console.log('Окно входа Master Vision открыто. Войдите в АВО; после подтверждения входа окно закроется.');
    await page.goto(CATALOG, { waitUntil: 'domcontentloaded', timeout: 45000 });
    // No login countdown: do not close the window while the user is signing in.
    await page.locator('#training-grid').waitFor({ state: 'attached', timeout: 0 });
    const response = await browser.request.get(CATALOG, { maxRedirects: 0, timeout: 45000 });
    try {
      const body = await response.text();
      if (!isCatalog(page.url(), response.status(), body) || !isCatalog(response.url(), response.status(), body)) {
        throw new Error('login_not_confirmed');
      }
    } finally { await response.dispose(); }
    verified = true;
    await browser.close(); // Flush only this isolated persistent profile cleanly.
    console.log('Вход Master Vision подтверждён и сохранён. Сборщик ещё не запущен.');
  } catch (_) {
    // Keep an unconfirmed login window open for the user. Closing it is explicit.
    if (browser.pages().length) {
      console.error('Вход Master Vision не подтверждён. Окно оставлено открытым; закройте его после проверки.');
      await new Promise(resolve => browser.once('close', resolve));
    }
    throw new Error(verified ? 'login_profile_close_failed' : 'login_not_confirmed');
  }
}

if (require.main === module) run().catch(() => {
  console.error('Вход Master Vision не сохранён или не подтверждён.');
  process.exitCode = 1;
});

module.exports = { CATALOG, PROFILE, loadPlaywright, isCatalog };
