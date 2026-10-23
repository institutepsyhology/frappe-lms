# Incremental build against the already verified, pinned production base image.
# Build with the complete source checkout as context; exclude .git/node_modules
# with a dedicated temporary build context or the release packaging helper.
ARG BASE_IMAGE=company-lms:lms-2.64.0-frappe-16.53.0
FROM ${BASE_IMAGE}

USER frappe
WORKDIR /home/frappe/frappe-bench
COPY --chown=frappe:0 source/ apps/lms/
COPY --chown=frappe:0 russian-source-manifest.json russian-source-manifest.json

RUN env/bin/python apps/lms/check-russian-translations.py
# Vite imports this public compile-time port. The runtime image deliberately
# carries no site-specific configuration; never copy the server's real config.
RUN env/bin/python -c "import json; from pathlib import Path; p=Path('sites/common_site_config.json'); config=json.loads(p.read_text()); config.setdefault('socketio_port',9000); p.write_text(json.dumps(config))"
RUN cd apps/lms/frontend && NODE_OPTIONS=--max-old-space-size=4096 yarn build
RUN env/bin/python -c "from pathlib import Path; from babel.messages.pofile import read_po; from babel.messages.mofile import write_mo; p=Path('assets/locale/ru/LC_MESSAGES/lms.mo'); p.parent.mkdir(parents=True,exist_ok=True); catalog=read_po(open('apps/lms/lms/locale/ru.po',encoding='utf-8'),locale='ru'); write_mo(open(p,'wb'),catalog,use_fuzzy=False)"

LABEL org.opencontainers.image.source="https://github.com/institutepsyhology/frappe-lms"
LABEL org.opencontainers.image.version="2.64.0-ru.20261024"
