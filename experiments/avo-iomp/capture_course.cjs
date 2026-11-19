'use strict';

const { spawnSync } = require('node:child_process');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const { loadPlaywright } = require('../mastervision-migration/login.cjs');
const { COURSE_PATH, ORIGIN, PROFILE, isCourseEditor } = require('./login.cjs');

const LESSON_PATH = '/shop/training/traininglessons/admin/update';
const CATALOG_PATH = '/shop/training/admin/admin';
const ARCHIVE = path.resolve(__dirname, '../../../exports/lesson-content/iomp/captured');
const MAX_HTML_BYTES = 32 * 1024 * 1024;

function editorUrl(page, id) {
  if (!Number.isSafeInteger(id) || id < 1 || id > 2147483647) throw new Error('invalid_source_id');
  return `${ORIGIN}${page}?id=${id}&lg=ru`;
}

function writeJson(file, data) {
  const temporary = `${file}.${process.pid}.tmp`;
  fs.writeFileSync(temporary, JSON.stringify(data) + '\n', { flag: 'wx' });
  fs.renameSync(temporary, file);
}

async function readEditor(browser, url, fields) {
  const response = await browser.request.get(url, { maxRedirects: 0, timeout: 45000 });
  try {
    const status = response.status();
    if (response.url() !== url || status === 401 || status === 403 || (status >= 300 && status < 400)) {
      throw new Error('editor_session_or_response_invalid');
    }
    if (!response.ok()) throw new Error('editor_http_error');
    const contentType = response.headers()['content-type'] || '';
    const bytes = await response.body();
    if (!/^text\/html\b/i.test(contentType) || bytes.length > MAX_HTML_BYTES) throw new Error('editor_response_invalid');
    const parser = spawnSync('py', ['-3', '-B', path.join(__dirname, 'parse_editor.py')], {
      input: JSON.stringify({ ...fields, html: bytes.toString('utf8') }), encoding: 'utf8',
      timeout: 45000, maxBuffer: 64 * 1024 * 1024, windowsHide: true,
    });
    if (parser.status !== 0 || !parser.stdout) throw new Error('editor_parse_failed');
    const parsed = JSON.parse(parser.stdout);
    if (!parsed.result) throw new Error(parsed.error || 'editor_parse_failed');
    return { ...parsed.result, source_sha256: crypto.createHash('sha256').update(bytes).digest('hex') };
  } finally {
    await response.dispose();
  }
}

function courseIdentity(course) {
  return JSON.stringify([course.course_id, course.title, course.lessons.map(({ id, title }) => [id, title])]);
}

async function openBrowser() {
  if (!fs.existsSync(path.join(PROFILE, 'Local State'))) throw new Error('iomp_login_required');
  return loadPlaywright().chromium.launchPersistentContext(PROFILE, {
    channel: 'msedge', headless: true, chromiumSandbox: true,
  });
}

async function readCatalog(browser) {
  let url = `${ORIGIN}${CATALOG_PATH}?lg=ru`;
  let total = null;
  const courses = new Map();
  for (let page = 1; url; page += 1) {
    const target = new URL(url);
    if (target.origin !== ORIGIN || target.pathname !== CATALOG_PATH ||
        target.username || target.password || target.hash || page > 1000) throw new Error('catalog_url_invalid');
    const chunk = await readEditor(browser, url, { kind: 'catalog', page });
    if (total === null) total = chunk.total;
    if (chunk.total !== total || chunk.start !== courses.size + 1 || chunk.end > 20000) {
      throw new Error('catalog_changed_during_capture');
    }
    for (const entry of chunk.courses) {
      if (courses.has(entry.id)) throw new Error('catalog_duplicate_course');
      courses.set(entry.id, entry);
    }
    url = chunk.next_url;
  }
  if (courses.size !== total) throw new Error('catalog_incomplete');
  return [...courses.values()].sort((a, b) => a.id - b.id);
}

function reusableLessons(folder, course) {
  const names = fs.readdirSync(folder).filter(name => /^\d{4}-\d{2}-\d{2}T/.test(name) &&
    fs.existsSync(path.join(folder, name, 'capture-status.json'))).sort();
  const latest = names.at(-1);
  if (!latest) throw new Error('partial_capture_missing');
  const base = path.join(folder, latest);
  const read = file => JSON.parse(fs.readFileSync(file, 'utf8'));
  const status = read(path.join(base, 'capture-status.json'));
  const ids = JSON.stringify(course.lesson_ids);
  if (status.account !== 'iomp' || status.course_id !== course.course_id || !status.outline_verified ||
      JSON.stringify(status.lesson_ids) !== ids || courseIdentity(read(path.join(base, 'course.json'))) !== courseIdentity(course)) {
    throw new Error('course_changed_before_repair');
  }
  const files = new Map();
  function add(directory, lessons) {
    for (const id of lessons) {
      if (!course.lesson_ids.includes(id)) throw new Error('repair_lesson_mismatch');
      files.set(id, path.join(directory, `lesson-${id}.json`));
    }
  }
  add(base, status.saved);
  const refreshed = path.join(folder, 'refreshed');
  if (fs.existsSync(refreshed)) {
    for (const name of fs.readdirSync(refreshed).filter(n => n >= latest).sort()) {
      const directory = path.join(refreshed, name);
      const receipt = path.join(directory, 'refresh-status.json');
      if (!fs.existsSync(receipt)) continue;
      const row = read(receipt);
      if (row.account !== 'iomp' || row.course_id !== course.course_id || JSON.stringify(row.lesson_ids) !== ids) {
        throw new Error('refreshed_outline_mismatch');
      }
      add(directory, row.refreshed);
    }
  }
  return { files, complete: status.issues.length === 0 && JSON.stringify(status.saved) === ids };
}

async function captureCourse(browser, courseId, limit, repair = false) {
  const courseUrl = editorUrl(COURSE_PATH, courseId);
  const courseRequest = { kind: 'course', course_id: courseId };
  const course = await readEditor(browser, courseUrl, courseRequest);
  if (!isCourseEditor(courseUrl, course.course_id) || course.course_id !== courseId) throw new Error('course_id_mismatch');
  const folder = path.join(ARCHIVE, `course-${courseId}`);
  const prior = repair ? reusableLessons(folder, course) : null;
  if (prior?.complete) return { course_id: courseId, already_complete: true };
  const reuse = prior?.files ?? new Map();
  const directory = path.join(folder, new Date().toISOString().replace(/[:.]/g, '-'));
  fs.mkdirSync(directory, { recursive: true });
  writeJson(path.join(directory, 'course.json'), course);
  const saved = [];
  const issues = [];
  let consecutive = 0;
  for (const lesson of course.lessons.slice(0, limit)) {
    if (fs.existsSync(path.join(ARCHIVE, 'STOP'))) throw new Error('paused_by_owner');
    const target = path.join(directory, `lesson-${lesson.id}.json`);
    if (reuse.has(lesson.id)) {
      fs.linkSync(reuse.get(lesson.id), target);
      saved.push(lesson.id);
      consecutive = 0;
      continue;
    }
    if (repair) {
      const disk = fs.statfsSync(ARCHIVE);
      if (disk.bavail * disk.bsize < 768 * 1024 * 1024) throw new Error('local_disk_reserve');
    }
    try {
      const capture = await readEditor(browser, editorUrl(LESSON_PATH, lesson.id), {
        kind: 'lesson', course_id: courseId, lesson_id: lesson.id,
        course_title: course.title, lesson_title: lesson.title,
      });
      writeJson(target, capture);
      saved.push(lesson.id);
      consecutive = 0;
    } catch (error) {
      const code = diagnostic(error);
      issues.push({ lesson_id: lesson.id, code });
      if (authLost(code)) throw error;
      if (++consecutive >= 10) break;
    }
  }
  const latest = await readEditor(browser, courseUrl, courseRequest);
  const status = {
    account: 'iomp', course_id: courseId, lesson_ids: course.lesson_ids, saved, issues,
    outline_verified: courseIdentity(course) === courseIdentity(latest),
  };
  writeJson(path.join(directory, 'capture-status.json'), status);
  return { ...status, directory };
}

async function run(courseId, limit) {
  const browser = await openBrowser();
  try {
    console.log(JSON.stringify(await captureCourse(browser, courseId, limit)));
  } finally {
    await browser.close();
  }
}

function diagnostic(error) {
  return /^[a-z_]{1,100}$/.test(error?.message || '') ? error.message : 'capture_failed';
}

function authLost(code) {
  return ['editor_session_or_response_invalid', 'source_auth_error', 'iomp_login_required'].includes(code);
}

if (require.main === module) {
  const [courseId, limit = '5', extra] = process.argv.slice(2);
  if (courseId === '--complete-missing' && process.argv.length === 4 && /^[1-9]\d*(?:,[1-9]\d*)*$/.test(limit)) {
    (async () => {
      const browser = await openBrowser();
      try {
        for (const id of new Set(limit.split(',').map(Number))) {
          const row = await captureCourse(browser, id, undefined, true);
          console.log(JSON.stringify({ course_id: id, already_complete: row.already_complete,
            outline_verified: row.outline_verified, saved: row.saved?.length, issues: row.issues }));
        }
      } finally { await browser.close(); }
    })().catch(error => { console.error(diagnostic(error)); process.exitCode = 1; });
  } else if (!/^[1-9][0-9]{0,9}$/.test(courseId || '') || !/^(?:[1-9]|10)$/.test(limit) || extra !== undefined) {
    console.error('Usage: node capture_course.cjs COURSE_ID [LIMIT 1-10]');
    process.exitCode = 1;
  } else {
    run(Number(courseId), Number(limit)).catch(error => {
      console.error(JSON.stringify({ error: diagnostic(error) }));
      process.exitCode = 1;
    });
  }
}

module.exports = { ARCHIVE, authLost, captureCourse, diagnostic, editorUrl, LESSON_PATH, openBrowser, readCatalog, readEditor, reusableLessons, writeJson };
