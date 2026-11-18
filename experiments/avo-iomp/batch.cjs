'use strict';

const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const { ARCHIVE, authLost, captureCourse, diagnostic, openBrowser, readCatalog, writeJson } = require('./capture_course.cjs');

const JOURNAL = path.join(ARCHIVE, 'batch-events.jsonl');
const REVIEW_LOG = path.join(ARCHIVE, 'batch-review.jsonl');
const LOCK = path.join(ARCHIVE, 'batch.lock');
const STOP = path.join(ARCHIVE, 'STOP');
const REVIEW_LIMIT = 10;

function event(value) {
  const line = JSON.stringify({ at: new Date().toISOString(), account: 'iomp', ...value });
  fs.appendFileSync(JOURNAL, line + '\n');
  if (value.status === 'review' || value.status === 'stopped' || value.cover_issue) {
    fs.appendFileSync(REVIEW_LOG, line + '\n');
  }
  console.log(line);
}

function recentEvents() {
  if (!fs.existsSync(JOURNAL)) return new Map();
  const rows = fs.readFileSync(JOURNAL, 'utf8').split(/\r?\n/).filter(Boolean).map(line => JSON.parse(line));
  return new Map(rows.filter(row => row.account === 'iomp' && Number.isSafeInteger(row.course_id))
    .map(row => [row.course_id, row]));
}

function priorCapture(courseId) {
  const folder = path.join(ARCHIVE, `course-${courseId}`);
  if (!fs.existsSync(folder)) return null;
  for (const name of fs.readdirSync(folder).sort().reverse()) {
    if (!/^\d{4}-\d{2}-\d{2}T/.test(name)) continue;
    const directory = path.join(folder, name);
    const file = path.join(directory, 'capture-status.json');
    if (!fs.existsSync(file)) continue;
    const capture = JSON.parse(fs.readFileSync(file, 'utf8'));
    if (capture.account === 'iomp' && capture.course_id === courseId && capture.outline_verified &&
        Array.isArray(capture.lesson_ids) && Array.isArray(capture.saved) &&
        Array.isArray(capture.issues) && !capture.issues.length &&
        JSON.stringify(capture.lesson_ids) === JSON.stringify(capture.saved)) return { ...capture, directory };
  }
  return null;
}

function importCourse(capture) {
  const processResult = spawnSync('py', ['-3', '-B', path.join(__dirname, 'import_capture.py'), capture.directory], {
    encoding: 'utf8', windowsHide: true, maxBuffer: 1024 * 1024,
  });
  if (processResult.status !== 0 || !processResult.stdout) throw new Error('frappe_result_uncertain');
  const result = JSON.parse(processResult.stdout);
  if (result.account !== 'iomp' || result.course_id !== String(capture.course_id) ||
      !['imported', 'excluded', 'review', 'stopped'].includes(result.status)) throw new Error('frappe_result_uncertain');
  return result;
}

async function run({ mode, after, limit }) {
  fs.mkdirSync(ARCHIVE, { recursive: true });
  const lock = fs.openSync(LOCK, 'wx');
  fs.writeFileSync(lock, JSON.stringify({ pid: process.pid, mode }));
  let browser;
  try {
    if (fs.existsSync(STOP)) throw new Error('paused_by_owner');
    const previous = recentEvents();
    if ([...previous.values()].some(row => row.status === 'write_started' || row.status === 'stopped')) {
      throw new Error('prior_frappe_result_requires_review');
    }
    browser = await openBrowser();
    const catalog = await readCatalog(browser);
    writeJson(path.join(ARCHIVE, 'batch-catalog.json'), { account: 'iomp', origin: 'https://shop.iomp.ru', courses: catalog });
    const ready = catalog.filter(row => {
      const status = previous.get(row.id)?.status;
      if (row.id <= after) return false;
      if (mode === '--retry-review') return status === 'review';
      return !['imported', 'excluded', 'review', ...(mode === '--capture-only' ? ['captured'] : [])].includes(status);
    });
    const selected = ready.slice(0, limit);
    event({ status: 'started', mode, catalog_count: catalog.length, batch_count: selected.length });
    let consecutive = 0;
    for (const row of selected) {
      if (fs.existsSync(STOP)) throw new Error('paused_by_owner');
      const disk = fs.statfsSync(ARCHIVE);
      if (disk.bavail * disk.bsize < 768 * 1024 * 1024) throw new Error('local_disk_reserve');
      let capture;
      try {
        capture = priorCapture(row.id) || await captureCourse(browser, row.id, undefined);
      } catch (error) {
        const code = diagnostic(error);
        if (authLost(code)) throw error;
        event({ course_id: row.id, status: 'review', stage: 'capture', code });
        if (++consecutive >= REVIEW_LIMIT) throw new Error('ten_consecutive_reviews');
        continue;
      }
      if (!capture.outline_verified || capture.issues.length || capture.saved.length !== capture.lesson_ids.length) {
        event({ course_id: row.id, status: 'review', stage: 'capture', code: 'capture_incomplete', issues: capture.issues });
        if (++consecutive >= REVIEW_LIMIT) throw new Error('ten_consecutive_reviews');
        continue;
      }
      if (mode === '--capture-only') {
        event({ course_id: row.id, status: 'captured', lessons: capture.saved.length });
        consecutive = 0;
        continue;
      }
      event({ course_id: row.id, status: 'write_started', lessons: capture.saved.length });
      const result = importCourse(capture);
      const { course_id, account, ...details } = result;
      event({ course_id: row.id, ...details });
      if (result.status === 'stopped') throw new Error('frappe_result_uncertain');
      consecutive = result.status === 'review' ? consecutive + 1 : 0;
      if (consecutive >= REVIEW_LIMIT) throw new Error('ten_consecutive_reviews');
    }
    event({ status: 'batch_finished', batch_count: selected.length, pending_count: ready.length - selected.length });
  } catch (error) {
    event({ status: 'batch_stopped', code: diagnostic(error) });
    process.exitCode = 1;
  } finally {
    try { if (browser) await browser.close(); } finally {
      fs.closeSync(lock);
      fs.unlinkSync(LOCK);
    }
  }
}

const [mode, after = '2', limit = '317', extra] = process.argv.slice(2);
if (!['--capture-only', '--apply', '--retry-review'].includes(mode) || !/^\d{1,10}$/.test(after) ||
    !/^\d{1,3}$/.test(limit) || Number(limit) < 1 || extra !== undefined) {
  console.error('Usage: node batch.cjs --capture-only|--apply|--retry-review [AFTER_ID] [COURSE_LIMIT]');
  process.exitCode = 1;
} else {
  run({ mode, after: Number(after), limit: Number(limit) }).catch(error => {
    console.error(JSON.stringify({ status: 'batch_not_started', code: diagnostic(error) }));
    process.exitCode = 1;
  });
}
