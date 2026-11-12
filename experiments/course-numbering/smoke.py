"""MVC numbering smoke: rollback fixtures; isolate concurrency in one owned Series row."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import frappe
from lms.lms import avo_course_routes as routes, course_numbering as numbering
from lms.lms.api import create_lesson, delete_lesson, upsert_chapter

SITE = 'my-lk.mv-centr.ru'
BENCH_SITES = Path('/home/frappe/frappe-bench/sites')


def require(value, code):
    if not value:
        raise RuntimeError(code)


def schema():
    columns = frappe.db.sql('SHOW COLUMNS FROM `tabSeries` LIKE %s', ('current',), as_dict=True)
    require(columns and 'bigint' in columns[0]['Type'].lower()
            and 'unsigned' not in columns[0]['Type'].lower(), 'series_not_signed_bigint')
    for doctype in numbering.DOCTYPES:
        field = frappe.get_meta(doctype).get_field('custom_lms_id')
        require(field and field.read_only and field.no_copy and field.unique, 'number_field_not_protected')
        indexes = frappe.db.sql('SHOW INDEX FROM `tab' + doctype + '`', as_dict=True)
        keys = {}
        for row in indexes:
            if not row['Non_unique']:
                keys.setdefault(row['Key_name'], []).append(row['Column_name'])
        require(['custom_lms_id'] in keys.values(), 'single_column_unique_index_missing')


def counters():
    result = {}
    for doctype in numbering.DOCTYPES:
        key = numbering._series_name(doctype, 'mv-centr')
        rows = frappe.db.sql('SELECT `current` FROM `tabSeries` WHERE `name`=%s FOR UPDATE', (key,))
        require(len(rows) == 1, 'production_series_missing')
        result[doctype] = int(rows[0][0])
    return result


def imported_identity(target):
    require(target and target.get('lesson_name'), 'imported_example_missing')
    return tuple(tuple(frappe.db.get_value(doctype, target[key],
        ['custom_lms_id', 'custom_avo_account', 'custom_avo_id']))
        for doctype, key in (('LMS Course', 'course_name'), ('Course Lesson', 'lesson_name')))


def fixture(before, created):
    course = frappe.get_doc({'doctype': 'LMS Course', 'title': 'Numbering smoke ' + uuid4().hex,
        'short_introduction': 'Temporary check', 'description': 'Temporary check', 'published': 0,
        'instructors': [{'instructor': 'Administrator'}]}).insert()
    created.append(('LMS Course', course.name))
    chapter = upsert_chapter(title='Temporary check', course=course.name, is_scorm_package=False)
    created.append(('Course Chapter', chapter.name))
    names = [create_lesson(chapter.name), create_lesson(chapter.name)]
    created.extend(('Course Lesson', name) for name in names)
    docs = [frappe.get_doc('Course Lesson', name) for name in names]
    require(course.custom_lms_id == str(before['LMS Course'] + 1), 'course_counter_not_next')
    require([int(doc.custom_lms_id) for doc in docs] ==
        [before['Course Lesson'] + 1, before['Course Lesson'] + 2], 'lesson_counters_not_next')
    require(not course.published and all(doc.is_draft for doc in docs), 'fixture_not_draft')
    require(not frappe.db.count('LMS Enrollment', {'course': course.name}), 'fixture_has_enrollment')
    require(all(not doc.get(field) for doc in [course, *docs]
        for field in ('custom_avo_account', 'custom_avo_id')), 'native_provenance_not_empty')
    course_id, lesson_id = course.custom_lms_id, docs[0].custom_lms_id
    require(routes.resolve(course_id, lesson_id)['lesson_name'] == names[0], 'native_lookup_failed')
    require(routes.resolve_editor_by_lesson(lesson_id)['course_id'] == course_id, 'native_editor_lookup_failed')
    require(routes.get_editor_by_source(course_id, lesson_id)['lesson']['name'] == names[0], 'native_editor_read_failed')
    require(routes.save_editor_by_source(course_id, lesson_id, names[0], {'title': 'Temporary saved check'})['saved'], 'native_save_failed')
    require(routes.get_editor_by_source(course_id, lesson_id)['lesson']['title'] == 'Temporary saved check', 'native_save_readback_failed')
    deleted_id = docs[1].custom_lms_id
    delete_lesson(names[1], chapter.name)
    replacement = create_lesson(chapter.name)
    created.append(('Course Lesson', replacement))
    require(int(frappe.db.get_value('Course Lesson', replacement, 'custom_lms_id')) > int(deleted_id), 'deleted_id_reused')
    require(routes.resolve(course_id, deleted_id) is None, 'deleted_id_still_resolves')


def concurrency(before):
    key = 'LMS URL ID:smoke:' + uuid4().hex
    original = numbering._series_name
    require(not frappe.db.sql('SELECT `current` FROM `tabSeries` WHERE `name`=%s', (key,)), 'temporary_key_exists')
    barrier = Barrier(4)
    def worker():
        frappe.init(site=SITE, sites_path=str(BENCH_SITES))
        frappe.connect(); frappe.set_user('Administrator')
        try:
            barrier.wait(timeout=30)
            values = []
            for _ in range(2):
                values.append(int(numbering._next('Course Lesson', 'mv-centr')))
                frappe.db.commit()
            return values
        finally:
            frappe.db.rollback(); frappe.destroy()
    try:
        numbering._series_name = lambda doctype, account: key
        with ThreadPoolExecutor(max_workers=4) as pool:
            values = sorted(value for batch in pool.map(lambda _: worker(), range(4)) for value in batch)
        floor = numbering.SOURCE_FLOORS['mv-centr']['Course Lesson']
        require(values == list(range(floor + 1, floor + 9)), 'concurrent_ids_not_unique_and_consecutive')
        rows = frappe.db.sql('SELECT `current` FROM `tabSeries` WHERE `name`=%s FOR UPDATE', (key,))
        require(len(rows) == 1 and int(rows[0][0]) == floor + 8, 'concurrent_high_water_wrong')
    finally:
        numbering._series_name = original
        try:
            require(counters() == before, 'concurrency_changed_production_series')
        finally:
            frappe.db.sql('DELETE FROM `tabSeries` WHERE `name`=%s', (key,)); frappe.db.commit()


def main():
    require(Path.cwd().resolve() == BENCH_SITES, 'unexpected_bench_directory')
    frappe.init(site=SITE); frappe.connect(); frappe.set_user('Administrator')
    created, prior_patch = [], frappe.flags.in_patch
    try:
        require(frappe.local.site == SITE and frappe.session.user == 'Administrator', 'unexpected_site_or_user')
        schema(); original = routes.resolve('206', '809'); identity = imported_identity(original)
        before = counters(); frappe.flags.in_patch = True
        try:
            fixture(before, created)
        finally:
            frappe.db.rollback(); frappe.flags.in_patch = prior_patch
        require(all(not frappe.db.exists(doctype, name) for doctype, name in created), 'fixture_rollback_failed')
        require(counters() == before, 'fixture_counter_rollback_failed')
        concurrency(before)
        require(routes.resolve('206', '809') == original and imported_identity(original) == identity, 'imported_identity_changed')
        require(routes.canonical(original['course_name'], str(original['chapter_number']), str(original['lesson_number'])) ==
            {'course_id': '206', 'lesson_id': '809'}, 'imported_roundtrip_failed')
        frappe.db.commit()
        print(json.dumps({'schema_unique': True, 'draft_fixture_rolled_back': True, 'native_read_save': True,
            'deletion_increments': True, 'concurrent_unique': True, 'production_counters_unchanged': True, 'imported_roundtrip': True}))
    finally:
        frappe.db.rollback(); frappe.flags.in_patch = prior_patch; frappe.destroy()


if __name__ == '__main__':
    main()
