ARG BASE_IMAGE
FROM ${BASE_IMAGE}
USER frappe
WORKDIR /home/frappe/frappe-bench
ADD --chown=frappe:0 overlay.tar apps/lms/
RUN env/bin/python apps/lms/experiments/avo-course-editor/apply_live_delta.py && \
    env/bin/python apps/lms/lms/lms/test_avo_course_routes_unit.py -q && \
    cd apps/lms/frontend && \
    node node_modules/vitest/vitest.mjs run --maxWorkers=1 src/tests/avoCourseRoutes.test.ts src/tests/lessonForm.test.ts src/tests/lessonFormTeardown.test.ts src/tests/mobileNav.test.ts src/tests/ChapterRow.test.ts src/tests/courseDetailOutlet.test.ts src/tests/courseOutline.test.ts src/tests/studentLessonSidebar.test.ts src/tests/lessonLocking.test.ts src/tests/chapterRoute.test.ts && \
    NODE_OPTIONS=--max-old-space-size=4096 nice -n 10 yarn build
LABEL org.opencontainers.image.source="https://github.com/institutepsyhology/frappe-lms"
