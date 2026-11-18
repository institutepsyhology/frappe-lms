'use strict';

const { spawnSync } = require('node:child_process');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const { loadPlaywright } = require('../mastervision-migration/login.cjs');
const { COURSE_PATH, ORIGIN, PROFILE, isCourseEditor } = require('./login.cjs');

const LESSON_PATH = '/shop/training/traininglessons/admin/update';
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
    if (!response.ok() || response.url() !== url) throw new Error('editor_session_or_response_invalid');
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

async function run(courseId, limit) {
  const courseUrl = editorUrl(COURSE_PATH, courseId);
  if (!fs.existsSync(path.join(PROFILE, 'Local State'))) throw new Error('iomp_login_required');
  const browser = await loadPlaywright().chromium.launchPersistentContext(PROFILE, {
    channel: 'msedge', headless: true, chromiumSandbox: true,
  });
  try {
    const courseRequest = { kind: 'course', course_id: courseId };
    const course = await readEditor(browser, courseUrl, courseRequest);
    if (!isCourseEditor(courseUrl, course.course_id) || course.course_id !== courseId) throw new Error('course_id_mismatch');
    const directory = path.join(ARCHIVE, `course-${courseId}`, new Date().toISOString().replace(/[:.]/g, '-'));
    fs.mkdirSync(directory, { recursive: true });
    writeJson(path.join(directory, 'course.json'), course);
    const saved = [];
    const issues = [];
    for (const lesson of course.lessons.slice(0, limit)) {
      try {
        const capture = await readEditor(browser, editorUrl(LESSON_PATH, lesson.id), {
          kind: 'lesson', course_id: courseId, lesson_id: lesson.id,
          course_title: course.title, lesson_title: lesson.title,
        });
        writeJson(path.join(directory, `lesson-${lesson.id}.json`), capture);
        saved.push(lesson.id);
      } catch (error) {
        const code = diagnostic(error);
        issues.push({ lesson_id: lesson.id, code });
        if (code === 'editor_session_or_response_invalid') break;
      }
    }
    const latest = await readEditor(browser, courseUrl, courseRequest);
    const status = {
      account: 'iomp', course_id: courseId, lesson_ids: course.lesson_ids, saved, issues,
      outline_verified: courseIdentity(course) === courseIdentity(latest),
    };
    writeJson(path.join(directory, 'capture-status.json'), status);
    console.log(JSON.stringify({ ...status, directory }));
  } finally {
    await browser.close();
  }
}

function diagnostic(error) {
  return /^[a-z_]{1,100}$/.test(error?.message || '') ? error.message : 'capture_failed';
}

const [courseId, limit = '5', extra] = process.argv.slice(2);
if (!/^[1-9][0-9]{0,9}$/.test(courseId || '') || !/^(?:[1-9]|10)$/.test(limit) || extra !== undefined) {
  console.error('Usage: node capture_course.cjs COURSE_ID [LIMIT 1-10]');
  process.exitCode = 1;
} else {
  run(Number(courseId), Number(limit)).catch(error => {
    console.error(JSON.stringify({ error: diagnostic(error) }));
    process.exitCode = 1;
  });
}
