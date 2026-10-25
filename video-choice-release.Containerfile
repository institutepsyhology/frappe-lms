# The release runner verifies this local tag resolves to the reviewed image ID.
ARG BASE_IMAGE=company-lms:russian-2.64.0-20261024
FROM ${BASE_IMAGE}
USER frappe
WORKDIR /home/frappe/frappe-bench
COPY --chown=frappe:0 frontend/src/utils/index.js apps/lms/frontend/src/utils/index.js
COPY --chown=frappe:0 frontend/src/utils/videoChoice.ts apps/lms/frontend/src/utils/videoChoice.ts
COPY --chown=frappe:0 frontend/src/tests/videoChoice.test.ts apps/lms/frontend/src/tests/videoChoice.test.ts
RUN cd apps/lms/frontend && node node_modules/vitest/vitest.mjs run --maxWorkers=2 > /tmp/video-choice-tests.log 2>&1; status=$?; if [ "$status" = 0 ]; then tail -12 /tmp/video-choice-tests.log; else tail -90 /tmp/video-choice-tests.log; fi; exit "$status"
RUN cd apps/lms/frontend && NODE_OPTIONS=--max-old-space-size=4096 yarn build
LABEL org.opencontainers.image.source="https://github.com/institutepsyhology/frappe-lms"
LABEL org.opencontainers.image.version="2.64.0-ru.video-choice.20261026"
