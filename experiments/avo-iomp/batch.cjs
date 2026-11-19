'use strict';

const fs = require('node:fs');
const path = require('node:path');
const { ARCHIVE, authLost, captureCourse, diagnostic, openBrowser, readCatalog, writeJson } = require('./capture_course.cjs');
const { startImportWorker } = require('./import_worker.cjs');

const JOURNAL = path.join(ARCHIVE, 'batch-events.jsonl');
const REVIEW_LOG = path.join(ARCHIVE, 'batch-review.jsonl');
const LOCK = path.join(ARCHIVE, 'batch.lock');
const STOP = path.join(ARCHIVE, 'STOP');
const REVIEW_LIMIT = 10;
const archiveMode = mode => ['--from-archive', '--archive-prefixes'].includes(mode);

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

function priorCapture(courseId, latestOnly = false) {
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
    if (latestOnly) return null;
  }
  return null;
}

function savedCatalog(snapshot) {
  const { account, origin, courses } = snapshot;
  if (account !== 'iomp' || origin !== 'https://shop.iomp.ru' || !Array.isArray(courses) ||
      !courses.length || !courses.every((row, i) => Number.isSafeInteger(row.id) && row.id > 0 &&
        (!i || row.id > courses[i - 1].id))) throw new Error('saved_catalog_invalid');
  return courses;
}

function selectCourses(catalog, previous, { mode, after, limit, ids }) {
  const ready = catalog.filter(row => {
    const last = previous.get(row.id);
    if (mode === '--resume-empty') {
      return ids.has(row.id) && last?.status === 'stopped' && last.code === 'mcp_authentication_failed';
    }
    if (mode === '--retry-courses' || archiveMode(mode)) {
      return ids.has(row.id) && (last?.status === 'review' || (last?.status === 'imported' && last.cover_issue));
    }
    if (row.id <= after) return false;
    if (mode === '--retry-review') return last?.status === 'review';
    return !['imported', 'excluded', 'review', ...(mode === '--capture-only' ? ['captured'] : [])].includes(last?.status);
  });
  if (ids && ready.length !== ids.size) throw new Error('requested_courses_not_pending_review');
  return { ready, selected: ready.slice(0, limit) };
}

async function run(options) {
  const { mode } = options;
  fs.mkdirSync(ARCHIVE, { recursive: true });
  const lock = fs.openSync(LOCK, 'wx');
  fs.writeFileSync(lock, JSON.stringify({ pid: process.pid, mode }));
  let browser, worker;
  try {
    if (fs.existsSync(STOP)) throw new Error('paused_by_owner');
    const previous = recentEvents();
    if ([...previous.values()].some(row => row.status === 'write_started' || (row.status === 'stopped' &&
        !(mode === '--resume-empty' && options.ids.has(row.course_id) && row.code === 'mcp_authentication_failed')))) {
      throw new Error('prior_frappe_result_requires_review');
    }
    const catalogPath = path.join(ARCHIVE, 'batch-catalog.json');
    let catalog;
    if (archiveMode(mode)) {
      catalog = savedCatalog(JSON.parse(fs.readFileSync(catalogPath, 'utf8')));
    } else {
      browser = await openBrowser();
      catalog = await readCatalog(browser);
      writeJson(catalogPath, { account: 'iomp', origin: 'https://shop.iomp.ru', courses: catalog });
    }
    const { ready, selected } = selectCourses(catalog, previous, options);
    event({ status: 'started', mode, catalog_count: catalog.length, batch_count: selected.length });
    let consecutive = 0;
    for (const row of selected) {
      if (fs.existsSync(STOP)) throw new Error('paused_by_owner');
      let capture;
      try {
        capture = priorCapture(row.id, archiveMode(mode));
        if (!capture) {
          if (archiveMode(mode)) throw new Error('complete_capture_missing');
          const disk = fs.statfsSync(ARCHIVE);
          if (disk.bavail * disk.bsize < 768 * 1024 * 1024) throw new Error('local_disk_reserve');
          capture = await captureCourse(browser, row.id, undefined);
        }
      } catch (error) {
        const code = diagnostic(error);
        if (authLost(code) || code === 'local_disk_reserve') throw error;
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
      worker ??= startImportWorker();
      const result = await worker.importCourse(capture, mode === '--resume-empty', mode === '--archive-prefixes');
      const { course_id, account, ...details } = result;
      event({ course_id: row.id, ...details });
      if (result.status === 'stopped') throw new Error('frappe_result_uncertain');
      consecutive = result.status === 'review' && !(result.created > 0) ? consecutive + 1 : 0;
      if (consecutive >= REVIEW_LIMIT) throw new Error('ten_consecutive_reviews');
    }
    if (worker && !await worker.close()) throw new Error('frappe_result_uncertain');
    event({ status: 'batch_finished', batch_count: selected.length, pending_count: ready.length - selected.length });
  } catch (error) {
    event({ status: 'batch_stopped', code: diagnostic(error) });
    process.exitCode = 1;
  } finally {
    try {
      if (worker) await worker.close();
      if (browser) await browser.close();
    } finally {
      fs.closeSync(lock);
      fs.unlinkSync(LOCK);
    }
  }
}

function parseOptions(args) {
  const [mode, after = '2', limit = '317', extra] = args;
  if (mode === '--resume-empty' && args.length === 2 && /^[1-9]\d{0,9}$/.test(after)) {
    return { mode, ids: new Set([Number(after)]), limit: 1 };
  }
  if ((mode === '--retry-courses' || archiveMode(mode)) && args.length === 2 && /^(?:[1-9]\d{0,9})(?:,[1-9]\d{0,9})*$/.test(after)) {
    const ids = after.split(',').map(Number);
    if (new Set(ids).size === ids.length) return { mode, ids: new Set(ids), limit: ids.length };
  }
  if (['--capture-only', '--apply', '--retry-review'].includes(mode) && /^\d{1,10}$/.test(after) &&
      /^\d{1,3}$/.test(limit) && Number(limit) >= 1 && extra === undefined) return { mode, after: Number(after), limit: Number(limit) };
  throw new Error('invalid_batch_arguments');
}

if (require.main === module) {
  Promise.resolve().then(() => run(parseOptions(process.argv.slice(2)))).catch(error => {
    console.error(JSON.stringify({ status: 'batch_not_started', code: diagnostic(error) }));
    process.exitCode = 1;
  });
}

module.exports = { parseOptions, savedCatalog, selectCourses };
