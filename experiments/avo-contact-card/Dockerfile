ARG BASE_IMAGE=company-lms:avo-user-import-1794214377
FROM ${BASE_IMAGE}
USER frappe
WORKDIR /home/frappe/frappe-bench
ADD --chown=frappe:0 overlay.tar apps/lms/
RUN env/bin/python apps/lms/lms/test_avo_user_import_unit.py -q && \
    cd apps/lms/frontend && \
    node node_modules/vitest/vitest.mjs run --maxWorkers=1 src/tests/avoContactCard.test.ts src/tests/memberFormRoute.test.ts src/tests/membersSearch.test.ts && \
    NODE_OPTIONS=--max-old-space-size=1536 yarn build && \
    cd /home/frappe/frappe-bench && \
    env/bin/python -c "from pathlib import Path;from babel.messages.pofile import read_po;from babel.messages.mofile import write_mo;p=Path('assets/locale/ru/LC_MESSAGES/lms.mo');p.parent.mkdir(parents=True,exist_ok=True);catalog=read_po(open('apps/lms/lms/locale/ru.po',encoding='utf-8'),locale='ru');write_mo(open(p,'wb'),catalog,use_fuzzy=False)"
LABEL org.opencontainers.image.source="https://github.com/institutepsyhology/frappe-lms"
