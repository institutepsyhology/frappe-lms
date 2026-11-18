'use strict';

const { spawn } = require('node:child_process');
const path = require('node:path');
const readline = require('node:readline');

function startImportWorker(interpreter = process.env.IOMP_PYTHON, launch = spawn) {
  const args = [...(interpreter ? [] : ['-3']), '-B', path.join(__dirname, 'import_worker.py')];
  const child = launch(interpreter || 'py', args, { windowsHide: true, stdio: ['pipe', 'pipe', 'ignore'] });
  // Subprocess diagnostics can contain private remote responses. Treat any
  // transport failure as uncertain and leave the outstanding journal entry.
  child.on('error', () => {});
  child.stdin.on('error', () => {});
  const finished = new Promise(resolve => child.once('close', code => resolve(code)));
  const lines = readline.createInterface({ input: child.stdout, crlfDelay: Infinity })[Symbol.asyncIterator]();

  return {
    async importCourse(capture, resumeEmpty = false) {
      const request = { course_id: String(capture.course_id), directory: capture.directory };
      if (resumeEmpty) request.resume_empty = true;
      try {
        await new Promise((resolve, reject) => child.stdin.write(JSON.stringify(request) + '\n', 'utf8',
          error => error ? reject(error) : resolve()));
        const row = await lines.next();
        if (row.done || row.value.length > 1024 * 1024) throw new Error();
        const result = JSON.parse(row.value);
        if (result.account !== 'iomp' || result.course_id !== request.course_id ||
            !['imported', 'excluded', 'review', 'stopped'].includes(result.status)) throw new Error();
        return result;
      } catch {
        throw new Error('frappe_result_uncertain');
      }
    },

    async close() {
      if (!child.stdin.destroyed && !child.stdin.writableEnded) child.stdin.end();
      return (await finished) === 0;
    },
  };
}

module.exports = { startImportWorker };
