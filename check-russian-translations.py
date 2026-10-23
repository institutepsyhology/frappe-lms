"""Check current-template coverage and runtime safety of the Russian catalog.

Usage: python check-russian-translations.py
Requires Babel, already provided by the Frappe environment.
"""

from collections import Counter
import io
import json
from pathlib import Path
import re
import sys

from babel.messages.mofile import write_mo
from babel.messages.pofile import read_po

ROOT = Path(__file__).resolve().parent
NUMBERED = re.compile(r"\{\d+\}")
JINJA = re.compile(r"\{\{\s*(.*?)\s*\}\}")
PRINTF = re.compile(r"(?<!%)%(?:\([^)]+\))?[#0 +\-]*(?:\d+|\*)?(?:\.(?:\d+|\*))?[diouxXeEfFgGcrsa](?![A-Za-z])")


def tokens(value):
    return tuple(Counter(pattern.findall(value)) for pattern in (NUMBERED, JINJA, PRINTF))


def validate():
    with (ROOT / 'lms/locale/main.pot').open(encoding='utf-8') as stream:
        template = read_po(stream)
    with (ROOT / 'lms/locale/ru.po').open(encoding='utf-8') as stream:
        catalog = read_po(stream, locale='ru')
    errors = []
    for message in template:
        if not message.id:
            continue
        translated = catalog.get(message.id, message.context)
        if not translated or translated.fuzzy or not translated.string:
            errors.append({'id':message.id,'error':'missing or fuzzy translation'})
    for message in catalog:
        if not message.id:
            continue
        source = message.id if isinstance(message.id, tuple) else (message.id,)
        target = message.string if isinstance(message.string, tuple) else (message.string,)
        for value in target:
            if not value:
                errors.append({'id':message.id,'error':'empty translation'})
            elif not any(tokens(value) == tokens(original) for original in source):
                errors.append({'id':message.id,'error':'placeholder mismatch'})
            elif '\ufffd' in value:
                errors.append({'id':message.id,'error':'Unicode replacement character'})
        # Babel also auto-detects '% complete' as the Python '% c' format.
        # These strings use numbered JS placeholders and a literal percent sign.
        if not any(PRINTF.search(value) for value in source):
            message.flags.discard('python-format')
        for problem in message.check(catalog):
            errors.append({'id':message.id,'error':str(problem)})
    compiled = io.BytesIO()
    write_mo(compiled,catalog,use_fuzzy=False)
    report = {'template_messages':len(template),'russian_messages':len(catalog),'compiled_bytes':compiled.tell(),'errors':errors,'ok':not errors}
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return report


if __name__ == '__main__':
    sys.exit(0 if validate()['ok'] else 1)
