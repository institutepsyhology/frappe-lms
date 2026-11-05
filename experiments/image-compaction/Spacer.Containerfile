FROM company-lms:flat-verified-20261105
USER frappe
WORKDIR /home/frappe/frappe-bench
COPY --chown=frappe:0 lms/lms/avo_import.py lms/lms/avo_transform.py lms/lms/avo_html_fragment.py apps/lms/lms/lms/
COPY --chown=frappe:0 frontend/src/utils/index.js frontend/src/utils/lessonSpacer.ts apps/lms/frontend/src/utils/
COPY --chown=frappe:0 frontend/src/tests/lessonSpacer.test.ts apps/lms/frontend/src/tests/
RUN cd apps/lms/frontend && node node_modules/vitest/vitest.mjs run src/tests/lessonSpacer.test.ts --maxWorkers=1 && NODE_OPTIONS=--max-old-space-size=2048 yarn build
