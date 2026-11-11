ARG BASE_IMAGE=company-lms:credential-profiles-20261111-v1
FROM ${BASE_IMAGE}
USER frappe
WORKDIR /home/frappe/frappe-bench
ADD --chown=frappe:0 overlay.tar apps/lms/
RUN env/bin/python apps/lms/lms/lms/test_avo_user_import_unit.py -q && \
    env/bin/python apps/lms/lms/lms/test_avo_marketing_unit.py -q && \
    env/bin/python apps/lms/lms/lms/test_credential_profiles_unit.py -q && \
    cd apps/lms/frontend && \
    node node_modules/vitest/vitest.mjs run --maxWorkers=1 src/tests/settingsAccess.test.ts src/tests/asyncTranslations.test.ts src/tests/avoContactCard.test.ts src/tests/credentialProfiles.test.ts && \
    NODE_OPTIONS=--max-old-space-size=4096 nice -n 10 yarn build && \
    cd /home/frappe/frappe-bench && \
    env/bin/python -c "from pathlib import Path;from babel.messages.pofile import read_po;from babel.messages.mofile import write_mo;p=Path('assets/locale/ru/LC_MESSAGES/lms.mo');p.parent.mkdir(parents=True,exist_ok=True);catalog=read_po(open('apps/lms/lms/locale/ru.po',encoding='utf-8'),locale='ru');write_mo(open(p,'wb'),catalog,use_fuzzy=False)"
LABEL org.opencontainers.image.source="https://github.com/institutepsyhology/frappe-lms"
