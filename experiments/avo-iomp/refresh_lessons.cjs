'use strict';

const fs = require('node:fs');
const path = require('node:path');
const { COURSE_PATH } = require('./login.cjs');
const { ARCHIVE, diagnostic, editorUrl, LESSON_PATH, openBrowser, readEditor, writeJson } = require('./capture_course.cjs');

async function refresh(groups) {
  const browser = await openBrowser();
  try {
    for (const [courseId, requested] of groups) {
      const courseUrl = editorUrl(COURSE_PATH, courseId);
      const fields = { kind: 'course', course_id: courseId };
      const course = await readEditor(browser, courseUrl, fields);
      if (!requested.every(id => course.lesson_ids.includes(id))) throw new Error('lesson_not_in_current_course');
      const directory = path.join(ARCHIVE, `course-${courseId}`, 'refreshed', new Date().toISOString().replace(/[:.]/g, '-'));
      fs.mkdirSync(directory, { recursive: true });
      for (const id of requested) {
        const lesson = course.lessons.find(item => item.id === id);
        const capture = await readEditor(browser, editorUrl(LESSON_PATH, id), {
          kind: 'lesson', course_id: courseId, lesson_id: id,
          course_title: course.title, lesson_title: lesson.title,
        });
        writeJson(path.join(directory, `lesson-${id}.json`), capture);
      }
      const check = await readEditor(browser, courseUrl, fields);
      const identity = row => JSON.stringify([row.course_id, row.title, row.lessons.map(item => [item.id, item.title])]);
      if (identity(course) !== identity(check)) throw new Error('course_changed_during_refresh');
      writeJson(path.join(directory, 'refresh-status.json'), {
        account: 'iomp', course_id: courseId, lesson_ids: course.lesson_ids, refreshed: requested,
      });
      console.log(JSON.stringify({ course_id: courseId, refreshed: requested }));
    }
  } finally {
    await browser.close();
  }
}

const args = process.argv.slice(2);
if (!args.length || !args.every(arg => /^[1-9]\d{0,9}:(?:[1-9]\d{0,9})(?:,[1-9]\d{0,9})*$/.test(arg))) {
  console.error('Usage: node refresh_lessons.cjs COURSE_ID:LESSON_ID[,LESSON_ID] ...');
  process.exitCode = 1;
} else {
  const groups = args.map(arg => {
    const [course, lessons] = arg.split(':');
    return [Number(course), [...new Set(lessons.split(',').map(Number))]];
  });
  refresh(groups).catch(error => {
    console.error(JSON.stringify({ error: diagnostic(error) }));
    process.exitCode = 1;
  });
}
