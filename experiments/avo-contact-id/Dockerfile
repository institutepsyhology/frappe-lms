ARG BASE_IMAGE
FROM ${BASE_IMAGE}
USER frappe
WORKDIR /home/frappe/frappe-bench
ADD --chown=frappe:0 overlay.tar apps/lms/
RUN env/bin/python apps/lms/lms/lms/test_avo_contact_resolver_unit.py -q && \
    cd apps/lms/frontend && \
    node node_modules/vitest/vitest.mjs run --maxWorkers=1 src/tests/avoContactById.test.ts src/tests/avoContactCard.test.ts src/tests/memberFormRoute.test.ts && \
    NODE_OPTIONS=--max-old-space-size=2048 nice -n 10 yarn build
LABEL org.opencontainers.image.source="https://github.com/institutepsyhology/frappe-lms"
