'use strict';

const { parseLiteral } = require('./access_parser.cjs');
const { ORIGIN, server } = require('./capture_worker.cjs');
const { PROFILE, loadPlaywright } = require('../mastervision-migration/login.cjs');

function expect(value, message) {
  if (!value) throw Error(message);
}

function sourceLiteral(html, expression, required) {
  const matches = [...html.matchAll(expression)];
  if (!required && !matches.length) return null;
  expect(matches.length === 1, 'ambiguous_course_editor');
  return parseLiteral(html, matches[0].index + matches[0][0].length).value;
}

async function fetchPolicy(browser, id) {
  expect(Number.isSafeInteger(id) && id > 0, 'invalid_course_id');
  const url = ORIGIN + '/shop/training/admin/update?id=' + id + '&lg=ru';
  const response = await browser.request.get(url, {maxRedirects: 0, timeout: 45000});
  let html;
  try {
    expect(response.status() !== 404, 'course_editor_missing');
    expect(response.status() === 200 && response.url() === url, 'course_editor_unavailable');
    html = await response.text();
  } finally {
    await response.dispose();
  }
  // Parse the detached HTML form without loading images, frames or site scripts.
  const tag = html.match(/<form\b(?=[^>]*\bid=["']training-form["'])[^>]*>/i)?.[0];
  const action = tag?.match(/\baction=["']([^"']+)["']/i)?.[1].replace(/&amp;/gi, '&');
  expect(action && new URL(action, ORIGIN).href === url, 'wrong_course_form');
  const controls = html.match(/<input\b(?=[^>]*\bname="TrainingForm\[(?:start_date|end_date|always_show|permanent_lesson_access|permanent_lesson_access_days)\]")[^>]*>/gi) || [];
  // A select's options are separate from its start tag.
  const select = html.match(/<select\b(?=[^>]*\bname="TrainingForm\[start_date_used\]")[^>]*>[\s\S]*?<\/select>/i)?.[0];
  expect(select, 'missing_start_mode');
  const page = browser.pages().find(p => p.url() === 'about:blank') || await browser.newPage();
  const settings = await page.evaluate(markup => {
    const doc = new DOMParser().parseFromString(markup, 'text/html');
    const result = {};
    for (const input of doc.querySelectorAll('select,input')) {
      if (input.type === 'hidden') continue;
      const key = input.name.match(/^TrainingForm\[(\w+)\]$/)?.[1];
      if (!key || Object.hasOwn(result, key)) throw Error('duplicate_setting');
      result[key] = input.type === 'checkbox' ? Number(input.checked) : input.value;
    }
    return result;
  }, controls.join('') + select);
  for (const key of ['start_date_used', 'start_date', 'end_date', 'always_show', 'permanent_lesson_access', 'permanent_lesson_access_days'])
    expect(Object.hasOwn(settings, key), 'missing_course_setting');
  const tree = sourceLiteral(html, /['"]trainingLessonsTree['"]\s*:\s*/g, true);
  expect(Array.isArray(tree), 'unknown_lesson_tree');
  const seen = new Set(), drafts = [], lessonRules = {};
  function visit(row) {
    expect(row && Number(row.id_training) === id, 'wrong_lesson_course');
    if (row.id_training_lessons == null && Array.isArray(row.elements)) {
      row.elements.forEach(visit);
      return;
    }
    const lesson = Number(row.id_training_lessons);
    expect(Number.isSafeInteger(lesson) && lesson > 0 && !seen.has(lesson) && Number(row.id_training) === id, 'unconfirmed_lesson_id');
    seen.add(lesson);
    expect([0,1,'0','1'].includes(row.is_draft), 'unconfirmed_draft_flag');
    if (Number(row.is_draft)) drafts.push(lesson);
    const keys = ['day_access', 'start_date', 'check_report', 'request_report'];
    expect(keys.every(key => Object.hasOwn(row, key)), 'unconfirmed_lesson_schedule');
    const rule = Object.fromEntries(keys.map(key => [key, row[key]]));
    if (Number(rule.day_access) !== 0 || Number(rule.check_report) !== 0 ||
        Number(rule.request_report) !== 0 || !['0000-00-00 00:00:00', '', null].includes(rule.start_date)) {
      lessonRules[lesson] = rule;
    }
    for (const [key, value] of Object.entries(row)) {
      if (!Array.isArray(value) || !value.length) continue;
      if (key === 'children' || value.every(item => item && typeof item === 'object' && 'id_training_lessons' in item)) value.forEach(visit);
    }
  }
  tree.forEach(visit);
  const notice = sourceLiteral(html, /AWO\.APE\(\s*['"]#TrainingForm_no_access_info['"]\s*,\s*/g, Boolean(settings.always_show));
  return {course_id: id, source_origin: ORIGIN, captured_at: new Date().toISOString(), settings,
    no_access_info: notice || {}, draft_lesson_ids: drafts, source_lesson_count: seen.size, lesson_rules: lessonRules};
}

async function collectPolicies() {
  const sink = server();
  const browser = await loadPlaywright().chromium.launchPersistentContext(PROFILE,
    {channel: 'msedge', headless: true, chromiumSandbox: true, args: ['--disk-cache-size=1048576']});
  try {
    const status = await sink.call({op: 'status'});
    expect(status.state === 'complete', 'incomplete_cards');
    const {course_ids: pending} = await sink.call({op: 'policy_ids'});
    // Re-check the control course after collection even if a pilot copy exists.
    const ids = [...new Set([598, ...pending])];
    const problems = [];
    const perCourse = new Set(['course_editor_missing', 'missing_start_mode', 'missing_course_setting',
      'ambiguous_course_editor', 'unknown_lesson_tree', 'unconfirmed_lesson_id', 'unconfirmed_draft_flag',
      'unconfirmed_lesson_schedule']);
    for (const id of ids) {
      try {
        const policy = await fetchPolicy(browser, id);
        await sink.call({op: 'policy', policy});
      } catch (error) {
        if (id === 598 || !perCourse.has(error.message)) throw error;
        problems.push(id);
        console.log(JSON.stringify({course_id: id, status: error.message}));
      }
    }
    const remaining = await sink.call({op: 'policy_ids'});
    expect(remaining.course_ids.every(id => problems.includes(id)), 'incomplete_course_policies');
    console.log(JSON.stringify({course_policies_stored: ids.length - problems.length, missing: problems.length}));
  } finally {
    sink.close();
    await browser.close();
  }
}

if (require.main === module) collectPolicies().catch(error => {
  console.error(/^[a-z_]+$/.test(error.message) ? error.message : 'course_policy_capture_failed');
  process.exitCode = 1;
});
module.exports = {fetchPolicy};
