"""Stable numeric course/lesson URLs, independent of AVO provenance and docnames."""
from contextlib import contextmanager
from contextvars import ContextVar
import re

import frappe

# Frappe 16.53's standard tabSeries.current is a signed INT(11).
MAX_ID = (1 << 31) - 1
DOCTYPES = ('LMS Course', 'Course Lesson')
SOURCE_FLOORS = {
    # Complete saved AVO catalogue and accepted manifests, including exclusions.
    'mv-centr': {'LMS Course': 1016, 'Course Lesson': 10242},
    'mastervision': {'LMS Course': 0, 'Course Lesson': 0},
    'iomp': {'LMS Course': 0, 'Course Lesson': 0},
}
_import_source = ContextVar('lms_numeric_import_source', default=None)


def _account():
    from lms.lms.avo_import import SITE_ACCOUNTS
    row = SITE_ACCOUNTS.get(frappe.local.site)
    return row[0] if row else None


def _number(value):
    if type(value) is int:
        value = str(value)
    if (not isinstance(value, str) or not re.fullmatch(r'[1-9][0-9]{0,18}', value)
            or int(value) > MAX_ID):
        frappe.throw('Invalid numeric course or lesson ID.', frappe.ValidationError)
    return value


def _series_name(doctype, account):
    if doctype not in DOCTYPES or account not in SOURCE_FLOORS:
        frappe.throw('Unsupported numbering scope.', frappe.ValidationError)
    return 'LMS URL ID:' + account + ':' + doctype


def _configured_floor(doctype, account):
    floor = SOURCE_FLOORS[account][doctype]
    if floor is None or floor == 0:
        return 0
    if type(floor) is not int or floor <= 0 or floor > MAX_ID:
        frappe.throw('The complete AVO source ID reservation must be configured first.', frappe.ValidationError)
    return floor


def _floor(doctype, account):
    floor = _configured_floor(doctype, account)
    if not floor:
        frappe.throw('Native numbering is not enabled for this site.', frappe.ValidationError)
    return floor


def _reserve(doctype, account, floor):
    if type(floor) is not int or floor < 0 or floor > MAX_ID:
        frappe.throw('Invalid course or lesson sequence floor.', frappe.ValidationError)
    key = _series_name(doctype, account)
    frappe.db.sql('INSERT INTO `tabSeries` (`name`,`current`) VALUES (%s,%s) '
                  'ON DUPLICATE KEY UPDATE `current`=GREATEST(`current`,VALUES(`current`))', (key, floor))
    return key


def _next(doctype, account):
    key = _reserve(doctype, account, _floor(doctype, account))
    rows = frappe.db.sql('SELECT `current` FROM `tabSeries` WHERE `name`=%s FOR UPDATE', (key,))
    current = int(rows[0][0])
    if current >= MAX_ID:
        frappe.throw('Course or lesson sequence is exhausted.', frappe.ValidationError)
    value = current + 1
    frappe.db.sql('UPDATE `tabSeries` SET `current`=%s WHERE `name`=%s', (value, key))
    return str(value)


def _source(row, account):
    source_account, source_id = row.get('custom_avo_account'), row.get('custom_avo_id')
    if source_account in (None, '') and source_id in (None, ''):
        return None
    if source_account != account or source_id in (None, ''):
        frappe.throw('AVO identity does not match this site.', frappe.ValidationError)
    return _number(source_id)


@contextmanager
def importing_source(doctype, account, source_id):
    """Give one internally-created document its genuine AVO identity before insert."""
    frappe.only_for('System Manager')
    if account != _account() or doctype not in DOCTYPES:
        frappe.throw('AVO import does not match this site.', frappe.PermissionError)
    token = _import_source.set((doctype, account, _number(source_id)))
    try:
        yield
    finally:
        _import_source.reset(token)


def assign(doc, method=None):
    """Allocate inside the inserting document's transaction; never reset on deletion."""
    account = _account()
    if not account or doc.doctype not in DOCTYPES:
        return
    if not frappe.get_meta(doc.doctype).has_field('custom_lms_id'):
        frappe.throw('Course numbering schema must be installed first.', frappe.ValidationError)
    context = _import_source.get()
    trusted = bool(context and context[0] == doc.doctype)
    if trusted:
        _import_source.set(None)
        _, source_account, source_id = context
        existing = _source(doc, account)
        if existing and (existing != source_id or source_account != account):
            frappe.throw('AVO import identity changed.', frappe.PermissionError)
        doc.set('custom_avo_account', source_account)
        doc.set('custom_avo_id', source_id)
    source_id = _source(doc, account)
    supplied = doc.get('custom_lms_id')
    if source_id:
        if not trusted:
            frappe.only_for('System Manager')
        if supplied not in (None, '') and _number(supplied) != source_id:
            frappe.throw('The imported URL ID must match its AVO ID.', frappe.ValidationError)
        if frappe.db.exists(doc.doctype, {'custom_lms_id': source_id}):
            frappe.throw('This course or lesson number is already reserved.', frappe.ValidationError)
        _reserve(doc.doctype, account, max(_configured_floor(doc.doctype, account), int(source_id)))
        doc.set('custom_lms_id', source_id)
    else:
        if supplied not in (None, ''):
            frappe.throw('New course and lesson numbers are assigned automatically.', frappe.ValidationError)
        if not _configured_floor(doc.doctype, account):
            doc.set('custom_lms_id', None)
            return
        doc.set('custom_lms_id', _next(doc.doctype, account))


def validate_identity(doc, method=None):
    """Keep URL IDs and imported provenance immutable after insertion."""
    if not _account() or doc.doctype not in DOCTYPES or doc.is_new():
        return
    previous = doc.get_doc_before_save()
    if not previous:
        previous = frappe.db.get_value(doc.doctype, doc.name,
            ['custom_lms_id', 'custom_avo_account', 'custom_avo_id'], as_dict=True)
    if not previous or any(doc.get(field) != previous.get(field)
                           for field in ('custom_lms_id', 'custom_avo_account', 'custom_avo_id')):
        frappe.throw('Course and lesson IDs cannot be changed after creation.', frappe.PermissionError)


def _preflight(doctype, account):
    meta = frappe.get_meta(doctype)
    fields = ['name', 'creation'] + [field for field in
        ('custom_lms_id', 'custom_avo_account', 'custom_avo_id') if meta.has_field(field)]
    rows = frappe.get_all(doctype, fields=fields, order_by='creation asc, name asc', limit_page_length=0)
    reserved, sources = {}, set()
    floor = _configured_floor(doctype, account)
    for row in rows:
        source_id = _source(row, account)
        if source_id:
            if source_id in sources:
                frappe.throw('Duplicate AVO course or lesson identity.', frappe.ValidationError)
            sources.add(source_id)
        route_id = _number(row['custom_lms_id']) if row.get('custom_lms_id') not in (None, '') else source_id
        if route_id and source_id and route_id != source_id:
            frappe.throw('An existing URL ID conflicts with its AVO ID.', frappe.ValidationError)
        if route_id:
            if route_id in reserved:
                frappe.throw('Duplicate numeric course or lesson URL ID.', frappe.ValidationError)
            reserved[route_id] = row['name']
            floor = max(floor, int(route_id))
        row['numbering_id'] = route_id
    return rows, floor


def _fields(unique):
    return {doctype: [{'fieldname': 'custom_lms_id',
        'label': 'Course ID' if doctype == 'LMS Course' else 'Lesson ID',
        'fieldtype': 'Data', 'length': 20, 'read_only': 1, 'no_copy': 1,
        'search_index': 1, 'unique': int(unique[doctype]), 'insert_after': 'title'}]
        for doctype in DOCTYPES}


def execute(dry_run=False):
    """Preserve source IDs, number existing native rows, then enforce uniqueness."""
    from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
    account = _account()
    if not account:
        raise RuntimeError('unsupported_numbering_site')
    plans = {doctype: _preflight(doctype, account) for doctype in DOCTYPES}
    preview = {}
    for doctype, (rows, floor) in plans.items():
        series = frappe.db.sql('SELECT `current` FROM `tabSeries` WHERE `name`=%s', (_series_name(doctype, account),))
        high_water = max(floor, int(series[0][0]) if series else 0)
        native = sum(row['numbering_id'] is None for row in rows)
        enabled = bool(_configured_floor(doctype, account))
        if enabled and high_water + native > MAX_ID:
            frappe.throw('Course or lesson sequence is exhausted.', frappe.ValidationError)
        preview[doctype] = {'records': len(rows), 'numbering_enabled': enabled,
            'native_to_number': native if enabled else 0, 'native_pending': 0 if enabled else native,
            'source_ids_to_copy': sum(not row.get('custom_lms_id') and bool(row['numbering_id']) for row in rows),
            'reserved_source_floor': _configured_floor(doctype, account), 'high_water': high_water,
            'next_new_id': str(high_water + native + 1) if enabled and high_water + native < MAX_ID else None}
    if dry_run:
        return {'account': account, 'dry_run': True,
            'numbering_enabled': all(row['numbering_enabled'] for row in preview.values()), 'doctypes': preview}
    if any(not frappe.get_meta(doctype).has_field(field)
           for doctype in DOCTYPES for field in ('custom_avo_account', 'custom_avo_id')):
        from lms.lms.avo_mapping_fields import execute as mapping_fields
        mapping_fields()
    unique = {}
    for doctype in DOCTYPES:
        field = frappe.get_meta(doctype).get_field('custom_lms_id')
        unique[doctype] = bool(field and field.unique)
    # Newly installed fields allow NULL until the preflighted rows are backfilled.
    # Never temporarily remove an already-installed unique constraint on a rerun.
    create_custom_fields(_fields(unique), update=True)
    result = {}
    for doctype, (rows, floor) in plans.items():
        _reserve(doctype, account, floor)
        enabled = preview[doctype]['numbering_enabled']
        changed = 0
        for row in rows:
            route_id = row['numbering_id'] or (_next(doctype, account) if enabled else None)
            if row.get('custom_lms_id') != route_id:
                frappe.db.set_value(doctype, row['name'], 'custom_lms_id', route_id, update_modified=False)
                changed += 1
        result[doctype] = {'backfilled': changed, 'source_floor': floor, 'numbering_enabled': enabled,
            'native_pending': preview[doctype]['native_pending']}
    create_custom_fields(_fields({doctype: True for doctype in DOCTYPES}), update=True)
    return {'account': account, 'dry_run': False,
        'numbering_enabled': all(row['numbering_enabled'] for row in result.values()), 'doctypes': result}
