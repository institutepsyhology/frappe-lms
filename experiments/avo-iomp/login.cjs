'use strict';

const fs = require('node:fs');
const path = require('node:path');
const { loadPlaywright } = require('../mastervision-migration/login.cjs');

const ORIGIN = 'https://shop.iomp.ru';
const COURSE_PATH = '/shop/training/admin/update';
const COURSE_URL = `${ORIGIN}${COURSE_PATH}?id=2&lg=ru`;
const PROFILE = path.resolve(__dirname, '../../../exports/lesson-content/private-browser-profiles/iomp');

function isCourseEditor(url, courseId) {
  const parsed = new URL(url);
  return parsed.origin === ORIGIN && parsed.pathname === COURSE_PATH &&
    parsed.searchParams.getAll('id').join(',') === String(courseId);
}

async function login() {
  fs.mkdirSync(PROFILE, { recursive: true });
  const browser = await loadPlaywright().chromium.launchPersistentContext(PROFILE, {
    channel: 'msedge', headless: false, chromiumSandbox: true,
  });
  try {
    const page = browser.pages()[0] || await browser.newPage();
    await page.goto(COURSE_URL, { waitUntil: 'domcontentloaded', timeout: 45000 });
    console.log('Окно Edge «АВО ИОМП» открыто. Войдите в ИОМП.');
    await page.locator('input[name="TrainingForm[id_training]"][value="2"]').waitFor({ state: 'attached', timeout: 0 });
    const response = await browser.request.get(COURSE_URL, { maxRedirects: 0, timeout: 45000 });
    try {
      const html = await response.text();
      if (!response.ok() || !isCourseEditor(page.url(), 2) ||
          !isCourseEditor(response.url(), 2) || !html.includes('TrainingForm[id_training]')) {
        throw new Error('login_not_confirmed');
      }
    } finally {
      await response.dispose();
    }
    await browser.close();
    console.log('Вход в АВО ИОМП подтверждён.');
  } catch (error) {
    if (browser.pages().length) {
      console.error('Вход пока не подтверждён. Окно оставлено открытым.');
      await new Promise(resolve => browser.once('close', resolve));
    }
    process.exitCode = 1;
  }
}

if (require.main === module) {
  login().catch(() => {
    console.error('Не удалось запустить отдельное окно ИОМП.');
    process.exitCode = 1;
  });
}

module.exports = { ORIGIN, PROFILE, COURSE_PATH, isCourseEditor };
