'use strict';

const assert = require('node:assert/strict');
const { spawn } = require('node:child_process');
const test = require('node:test');
const { startImportWorker } = require('./import_worker.cjs');

test('one child processes replies in request order and closes on EOF', async () => {
  let starts = 0;
  const worker = startImportWorker('unused', (_executable, _args, options) => {
    starts++;
    const script = `
      const lines = require('node:readline').createInterface({ input: process.stdin });
      let count = 0;
      lines.on('line', line => {
        const row = JSON.parse(line);
        console.log(JSON.stringify({ account: 'iomp', status: 'imported', course_id: row.course_id,
          sequence: ++count, resume: row.resume_empty === true, directory: row.directory }));
      });
    `;
    return spawn(process.execPath, ['-e', script], options);
  });
  try {
    const first = await worker.importCourse({ course_id: 7, directory: 'уроки 7' });
    const next = await worker.importCourse({ course_id: 8, directory: 'уроки 8' }, true);
    assert.deepEqual([first.sequence, next.sequence], [1, 2]);
    assert.deepEqual([first.resume, next.resume], [false, true]);
    assert.deepEqual([first.directory, next.directory], ['уроки 7', 'уроки 8']);
    assert.equal(starts, 1);
  } finally {
    assert.equal(await worker.close(), true);
  }
});

test('truncated, mismatched or missing output stops the batch', async () => {
  for (const line of ['', '{', '{"account":"iomp","status":"imported","course_id":"2"}']) {
    const worker = startImportWorker('unused', (_executable, _args, options) =>
      spawn(process.execPath, ['-e', `process.stdin.once('data', () => {
        process.stdout.write(${JSON.stringify(line)}); process.stdin.destroy();
      })`], options));
    try {
      await assert.rejects(worker.importCourse({ course_id: 1, directory: 'capture' }),
        /frappe_result_uncertain/);
    } finally {
      await worker.close();
    }
  }
});
