ARG BASE_IMAGE
FROM ${BASE_IMAGE}
USER frappe
WORKDIR /home/frappe/frappe-bench
ADD --chown=frappe:0 overlay.tar apps/lms/
RUN env/bin/python apps/lms/lms/lms/test_course_numbering_unit.py -q && \
    env/bin/python apps/lms/lms/lms/test_avo_course_routes_unit.py -q && \
    env/bin/python apps/lms/lms/lms/test_avo_import_unit.py -q
LABEL org.opencontainers.image.source="https://github.com/institutepsyhology/frappe-lms"
