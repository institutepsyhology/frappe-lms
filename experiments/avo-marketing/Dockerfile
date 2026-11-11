ARG BASE_IMAGE=company-lms:marketing-20261111-v1
FROM ${BASE_IMAGE}
USER frappe
WORKDIR /home/frappe/frappe-bench
ADD --chown=frappe:0 overlay.tar apps/lms/
RUN env/bin/python apps/lms/lms/lms/test_avo_user_import_unit.py -q && \
    env/bin/python apps/lms/lms/lms/test_avo_marketing_unit.py -q && \
    test -s apps/lms/lms/www/_lms.html
LABEL org.opencontainers.image.source="https://github.com/institutepsyhology/frappe-lms"
