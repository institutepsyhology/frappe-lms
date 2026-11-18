'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');
const { parseOptions, selectCourses } = require('./batch.cjs');

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

test('empty-destination recovery is limited to a recorded failed login', () => {
  const options = parseOptions(['--resume-empty', '4']);
  const stop = code => new Map([[4, { status: 'stopped', code }]]);
  assert.deepEqual(selectCourses(catalog, stop('mcp_authentication_failed'), options).selected, [{ id: 4 }]);
  assert.throws(() => selectCourses(catalog, stop('write_result_uncertain'), options));
  assert.throws(() => selectCourses(catalog, previous, options));
});
