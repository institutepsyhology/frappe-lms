from pathlib import Path
from babel.messages.mofile import read_mo, write_mo

path = Path('/home/frappe/frappe-bench/assets/locale/ru/LC_MESSAGES/lms.mo')
with path.open('rb') as f:
    catalog = read_mo(f)
entry = catalog.get('section')
if not entry or entry.string not in ('Р Р°Р·РґРµР»', 'раздел'):
    raise SystemExit('Unexpected translation; refusing to modify')
entry.string = 'раздел'
with path.open('wb') as f:
    write_mo(f, catalog, use_fuzzy=True)
