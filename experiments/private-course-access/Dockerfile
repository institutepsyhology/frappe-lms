FROM sha256:d4a1f221ed802b0625963909334c067d0ba6f164563193519416537e8d9b2d8d
ARG SOURCE_REVISION=unknown
USER frappe
WORKDIR /home/frappe/frappe-bench
ADD --chown=frappe:0 overlay.tar apps/lms/
RUN cd apps/lms/frontend && \
    node node_modules/vitest/vitest.mjs run --maxWorkers=1 \
      src/tests/courseMemberVisibility.test.ts \
      src/tests/coursesDefaultTab.test.ts \
      src/tests/coursesFilters.test.ts \
      src/tests/courseDetailOutlet.test.ts && \
    NODE_OPTIONS=--max-old-space-size=4096 nice -n 10 yarn build
LABEL org.opencontainers.image.source="https://github.com/institutepsyhology/frappe-lms" \
      org.opencontainers.image.revision="${SOURCE_REVISION}" \
      ru.mvcentr.release="private-course-access-v1" \
      ru.mvcentr.baseline="sha256:d4a1f221ed802b0625963909334c067d0ba6f164563193519416537e8d9b2d8d"
