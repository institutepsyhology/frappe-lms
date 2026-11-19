'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const { parseOptions, savedCatalog, selectCourses } = require('./batch.cjs');
const { reusableLessons } = require('./capture_course.cjs');

const catalog = [4, 5, 6, 7, 8].map(id => ({ id }));
const previous = new Map([
  [4, { status: 'imported', cover_issue: 'jpeg_cover_requires_readback' }],
  [5, { status: 'review' }],
  [6, { status: 'excluded' }],
  [7, { status: 'imported' }],
]);

test('retry selected pending courses in source order', () => {
  const options = parseOptions(['--retry-courses', '5,4']);
  assert.deepEqual(selectCourses(catalog, previous, options).selected, catalog.slice(0, 2));
  for (const ids of ['4,6', '7', '8', '9']) {
    assert.throws(() => selectCourses(catalog, previous, parseOptions(['--retry-courses', ids])));
  }
});

test('automatic import still skips earlier outcomes and honors the limit', () => {
  assert.deepEqual(selectCourses(catalog, previous, parseOptions(['--apply', '2', '1'])).selected, [{ id: 8 }]);
  assert.deepEqual(selectCourses(catalog, previous, parseOptions(['--retry-review'])).selected, [{ id: 5 }]);
  for (const args of [['--retry-courses'], ['--retry-courses', '4,4'], ['--retry-courses', '4', '1']]) {
    assert.throws(() => parseOptions(args));
  }
});

test('archive mode accepts ordered IOMP IDs and only retries the requested courses', () => {
  const data = { account: 'iomp', origin: 'https://shop.iomp.ru', courses: catalog };
  const options = parseOptions(['--from-archive', '5,4']);
  assert.deepEqual(selectCourses(savedCatalog(data), previous, options).selected, catalog.slice(0, 2));
  assert.throws(() => savedCatalog({ ...data, account: 'mastervision' }));
  assert.throws(() => savedCatalog({ ...data, origin: 'https://shop.mv-centr.ru' }));
  assert.throws(() => savedCatalog({ ...data, courses: [catalog[0], catalog[0]] }));
});

test('partial repair reuses archived lessons and newer verified refreshes in the same outline', t => {
  const base = 'archive', stamp = '2026-11-19T12-00', newer = '2026-11-20T12-00';
  const course = { course_id: 7, title: 'course', lesson_ids: [8, 9], lessons: [{ id: 8, title: 'one' }, { id: 9, title: 'two' }] };
  const status = { account: 'iomp', course_id: 7, outline_verified: true, lesson_ids: [8, 9], saved: [8], issues: [{}] };
  const receipt = { account: 'iomp', course_id: 7, lesson_ids: [8, 9], refreshed: [8] };
  const rows = { 'course.json': course, 'capture-status.json': status, 'refresh-status.json': receipt };
  t.mock.method(fs, 'readdirSync', p => path.basename(p) === 'refreshed' ? [newer] : [stamp, 'refreshed']);
  t.mock.method(fs, 'existsSync', () => true);
  t.mock.method(fs, 'readFileSync', p => JSON.stringify(rows[path.basename(p)]));
  const result = reusableLessons(base, course);
  assert.equal(result.complete, false);
  assert.deepEqual([...result.files], [[8, path.join(base, 'refreshed', newer, 'lesson-8.json')]]);
  assert.throws(() => reusableLessons(base, { ...course, title: 'renamed' }), /course_changed/);
  receipt.account = 'mastervision';
  assert.throws(() => reusableLessons(base, course), /refreshed_outline_mismatch/);
});

test('empty-destination recovery is limited to a recorded failed login', () => {
  const options = parseOptions(['--resume-empty', '4']);
  const stop = code => new Map([[4, { status: 'stopped', code }]]);
  assert.deepEqual(selectCourses(catalog, stop('mcp_authentication_failed'), options).selected, [{ id: 4 }]);
  assert.throws(() => selectCourses(catalog, stop('write_result_uncertain'), options));
  assert.throws(() => selectCourses(catalog, previous, options));
});
