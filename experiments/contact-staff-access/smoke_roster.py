"""Real MariaDB/controller smoke checks for a disposable initialized stage.

Never operates on a live site or contacts external services. Application rows
are rolled back; a minimal AVO ledger schema may remain on the disposable stage.
The returned report contains booleans and counts only.
"""
import json
import uuid
from datetime import timedelta

import frappe
from frappe.utils import add_to_date, get_datetime, now_datetime


def _ledger_schema():
    if frappe.db.exists('DocType', 'AVO Course Access'):
        return
    # The production ledger is a custom DocType created by the archive importer,
    # so a fresh app-only stage has no JSON-backed schema to reload for it.
    specs = [
        ('account', 'Data', None), ('source_access_id', 'Data', None),
        ('source_contact_id', 'Data', None), ('source_course_id', 'Data', None),
        ('source_snapshot_hash', 'Data', None), ('payload_hash', 'Data', None),
        ('source_payload', 'Long Text', None), ('captured_at', 'Datetime', None),
        ('mapped_user', 'Link', 'User'), ('mapped_contact', 'Link', 'Contact'),
        ('mapped_course', 'Link', 'LMS Course'), ('grant', 'Link', 'LMS Access Grant'),
        ('enrollment', 'Link', 'LMS Enrollment'),
        ('sync_status', 'Select', 'Stored\nPending Contact\nPending Course\nNeeds Review\nApplied\nFrozen\nExpired\nSuperseded'),
        ('review_reason', 'Data', None),
    ]
    fields = []
    for name, kind, options in specs:
        row = {'fieldname': name, 'label': name.replace('_', ' ').title(), 'fieldtype': kind}
        if options:
            row['options'] = options
        fields.append(row)
    frappe.get_doc({'doctype': 'DocType', 'name': 'AVO Course Access', 'module': 'LMS',
        'custom': 1, 'autoname': 'hash', 'fields': fields,
        'permissions': [{'role': 'System Manager', 'read': 1, 'write': 1, 'create': 1}]}).insert(ignore_permissions=True)


def _bulk(table, fields, values):
    frappe.db.bulk_insert(table, fields, values)


def run():
    site = getattr(frappe.local, 'site', '')
    if not isinstance(site, str) or not site.endswith('.local') or 'stage' not in site:
        raise RuntimeError('isolated_stage_required')

    from lms.lms import course_people as people
    from lms.lms.access_blocks import is_blocked
    from lms.lms.individual_access import grant_allows_lesson
    from lms.lms.staff_policy import clear_policy_cache
    from lms.lms.staff_positions import save_employee, save_position

    checks = {key: False for key in (
        'fixtures_ready', 'default_page_fifty', 'all_page_sizes', 'next_page_no_overlap',
        'global_sort_both_directions', 'sort_injection_rejected', 'phone_fallback_actual',
        'effective_end_dates', 'opaque_pair_read', 'person_lesson_page',
        'contact_privacy_mask', 'name_email_privacy_mask', 'hidden_sort_denied',
        'course_block_all_grants', 'course_unblock', 'lesson_timed_block',
        'source_immutable_after_removal', 'all_grants_revoked', 'enrollment_removed',
        'user_and_progress_preserved', 'course_count_updated',
    )}
    checks.update(fixture_students=205, failure_step=0)
    previous_user = frappe.session.user
    old_release = frappe.conf.get('individual_access_release_enabled')
    had_release = 'individual_access_release_enabled' in frappe.conf
    had_account = site in people.SITE_ACCOUNTS
    old_account = people.SITE_ACCOUNTS.get(site)
    prefix = 'roster-smoke-' + uuid.uuid4().hex[:10]
    step = 1
    try:
        frappe.set_user('Administrator'); clear_policy_cache()
        _ledger_schema()  # Any schema DDL happens before the rollback-only fixtures.
        # Bind the disposable stage to the source-account namespace under test.
        # This changes request-local configuration only, never a production map.
        people.SITE_ACCOUNTS[site] = 'mv-centr'
        frappe.conf.individual_access_release_enabled = True
        course = frappe.get_doc({'doctype': 'LMS Course', 'title': prefix,
            'description': 'Synthetic isolated roster checks.', 'short_introduction': 'Synthetic roster',
            'published': 0, 'disable_self_learning': 1,
            'instructors': [{'instructor': 'Administrator'}]}).insert(ignore_permissions=True)
        chapter = frappe.get_doc({'doctype': 'Course Chapter', 'title': prefix + ' chapter',
                                 'course': course.name}).insert(ignore_permissions=True)
        frappe.get_doc({'doctype': 'Chapter Reference', 'parent': course.name,
            'parenttype': 'LMS Course', 'parentfield': 'chapters', 'chapter': chapter.name, 'idx': 1}).insert(ignore_permissions=True)
        lesson = frappe.get_doc({'doctype': 'Course Lesson', 'course': course.name,
            'chapter': chapter.name, 'title': prefix + ' lesson',
            'content': json.dumps({'blocks': [{'type': 'paragraph', 'data': {'text': 'Synthetic lesson'}}]})}).insert(ignore_permissions=True)
        frappe.get_doc({'doctype': 'Lesson Reference', 'parent': chapter.name,
            'parenttype': 'Course Chapter', 'parentfield': 'lessons', 'lesson': lesson.name, 'idx': 1}).insert(ignore_permissions=True)

        base = get_datetime(now_datetime()) - timedelta(days=10)
        members = [prefix + '-' + str(i).zfill(4) + '@example.invalid' for i in range(205)]
        user_fields = ('name', 'email', 'first_name', 'full_name', 'username', 'enabled', 'user_type',
                       'mobile_no', 'creation', 'modified', 'owner', 'modified_by', 'docstatus', 'idx')
        _bulk('User', user_fields, [(member, member, 'Roster ' + str(i).zfill(4), 'Roster ' + str(i).zfill(4),
            prefix + '-' + str(i).zfill(4), 1, 'Website User', '' if i == 0 else '7000' + str(i).zfill(7),
            base, base, 'Administrator', 'Administrator', 0, 0) for i, member in enumerate(members)])
        enrollment_fields = ('name', 'course', 'member', 'member_name', 'member_username', 'member_type',
                              'role', 'progress', 'creation', 'modified', 'owner', 'modified_by', 'docstatus', 'idx')
        enrollments = [prefix + '-enrollment-' + str(i).zfill(4) for i in range(205)]
        _bulk('LMS Enrollment', enrollment_fields, [(enrollments[i], course.name, member,
            'Roster ' + str(i).zfill(4), prefix + '-' + str(i).zfill(4), 'Student', 'Member', i % 101,
            base + timedelta(minutes=i), base, member, 'Administrator', 0, 0) for i, member in enumerate(members)])
        frappe.db.set_value('LMS Course', course.name, 'enrollments', 205, update_modified=False)
        contact = frappe.get_doc({'doctype': 'Contact', 'first_name': 'Synthetic linked contact', 'user': members[0],
            'phone_nos': [{'phone': '79990009999', 'is_primary_mobile_no': 1}],
            'email_ids': [{'email_id': prefix + '-linked@example.invalid', 'is_primary': 1}]})
        if frappe.get_meta('Contact').has_field('custom_avo_account'):
            contact.custom_avo_account = 'mv-centr'
        contact.insert(ignore_permissions=True)
        policy = frappe.get_doc({'doctype': 'LMS Access Policy', 'course': course.name, 'enabled': 1,
            'default_personal_end_type': 'Unlimited', 'global_end_type': 'Unlimited',
            'completed_retention_type': 'None', 'visited_retention_type': 'None',
            'lessons': [{'lesson': lesson.name, 'opening_type': 'After Start', 'delay_days': 0, 'prerequisite_type': 'None'}]}).insert(ignore_permissions=True)
        first_grant = people.create_member_access(course.name, members[0])['name']
        end_personal, end_general = add_to_date(now_datetime(), days=5), add_to_date(now_datetime(), days=3)
        second = frappe.get_doc({'doctype': 'LMS Access Grant', 'course': course.name, 'member': members[1],
            'status': 'Active', 'starts_at': base, 'personal_end_type': 'At', 'ends_at': end_personal,
            'course_end_type': 'At', 'course_ends_at': end_general,
            'lessons': [{'lesson': lesson.name, 'opening_type': 'Inherit', 'prerequisite_state': 'Inherit'}]}).insert(ignore_permissions=True)
        checks['fixtures_ready'] = True

        step = 2
        default = people.list_students(course.name)
        checks['default_page_fifty'] = default['total'] == 205 and len(default['rows']) == 50 and default['page_length'] == 50
        checks['all_page_sizes'] = all(len(people.list_students(course.name, page_length=n)['rows']) == min(n, 205) for n in people.PAGE_LENGTHS)
        a = people.list_students(course.name, page=1, sort_by='full_name', sort_dir='asc')
        b = people.list_students(course.name, page=2, sort_by='full_name', sort_dir='asc')
        checks['next_page_no_overlap'] = not ({r['enrollment'] for r in a['rows']} & {r['enrollment'] for r in b['rows']})
        checks['global_sort_both_directions'] = all(
            people.list_students(course.name, sort_by=field, sort_dir='asc')['rows'][0]['member'] == members[0]
            and people.list_students(course.name, sort_by=field, sort_dir='desc')['rows'][0]['member'] == members[-1]
            for field in ('full_name', 'email', 'enrolled_at'))
        # Execute every other allowlisted sort in both directions on real MariaDB.
        for field in ('phone', 'starts_at', 'ends_at', 'progress'):
            for direction in ('asc', 'desc'):
                assert people.list_students(course.name, sort_by=field, sort_dir=direction)['total'] == 205
        try:
            people.list_students(course.name, sort_by='email;DELETE FROM User')
        except frappe.ValidationError:
            checks['sort_injection_rejected'] = True
        first = people.list_students(course.name, search=members[0])['rows'][0]
        checks['phone_fallback_actual'] = first['email'] == members[0] and first['phone'] == '79990009999'
        dated = people.list_students(course.name, search=members[1])['rows'][0]
        checks['effective_end_dates'] = get_datetime(dated['ends_at']) == get_datetime(end_general)
        token = first['enrollment']
        info = people.get_member_access(course.name, enrollment=token)
        checks['opaque_pair_read'] = info['member'] == members[0] and info['grants'][0]['name'] == first_grant
        lesson_page = people.list_member_lessons(course.name, enrollment=token, grant=first_grant)
        checks['person_lesson_page'] = lesson_page['total'] == 1 and lesson_page['rows'][0]['lesson'] == lesson.name
        alternate = frappe.get_doc({'doctype': 'LMS Access Grant', 'course': course.name, 'member': members[0],
            'status': 'Active', 'starts_at': base, 'personal_end_type': 'Unlimited', 'course_end_type': 'Unlimited',
            'lessons': [{'lesson': lesson.name, 'opening_type': 'Inherit', 'prerequisite_state': 'Inherit'}]}).insert(ignore_permissions=True)

        step = 3
        staff = frappe.get_doc({'doctype': 'User', 'email': prefix + '-staff@example.invalid',
            'first_name': 'Synthetic roster staff', 'user_type': 'Website User', 'send_welcome_email': 0,
            'roles': [{'role': 'LMS Student'}]}).insert(ignore_permissions=True)
        position = save_position({'title': prefix + ' course-only position', 'parent_position': None,
            'active': 1, 'course_scope': 'All', 'native_roles': ['LMS Student'],
            'permissions': [{'resource': 'course_access', 'action': action} for action in ('read', 'write', 'remove')]})
        save_employee(staff.name, position['name'])
        frappe.db.set_value('User', members[0], 'full_name', members[0], update_modified=False)
        frappe.set_user(staff.name); clear_policy_cache()
        masked = people.list_students(course.name)
        masked_info = people.get_member_access(course.name, enrollment=token)
        checks['contact_privacy_mask'] = all(not r.get('member') and not r.get('email') and not r.get('phone') and not r.get('avo_id') for r in masked['rows']) and '@example.invalid' not in json.dumps(masked_info, default=str)
        masked_first = people.list_students(course.name, sort_by='enrolled_at', sort_dir='asc')['rows'][0]
        checks['name_email_privacy_mask'] = masked_first['full_name'].startswith('Ученик ') and '@' not in masked_first['full_name']
        try:
            people.list_students(course.name, sort_by='email')
        except frappe.PermissionError:
            checks['hidden_sort_denied'] = True

        step = 4
        people.set_member_block(course.name, 1, enrollment=token)
        checks['course_block_all_grants'] = is_blocked(members[0], course.name) and not grant_allows_lesson(user=members[0], lesson=lesson.name)
        people.set_member_block(course.name, 0, enrollment=token)
        checks['course_unblock'] = not is_blocked(members[0], course.name) and grant_allows_lesson(user=members[0], lesson=lesson.name)
        until = add_to_date(now_datetime(), minutes=5)
        people.set_member_block(course.name, 1, enrollment=token, until=str(until), lesson=lesson.name)
        checks['lesson_timed_block'] = (is_blocked(members[0], course.name, lesson=lesson.name)
            and not is_blocked(members[0], course.name, lesson=lesson.name, now=add_to_date(until, seconds=1)))
        people.set_member_block(course.name, 0, enrollment=token, lesson=lesson.name)

        step = 5
        frappe.set_user('Administrator'); clear_policy_cache()
        progress = frappe.get_doc({'doctype': 'LMS Course Progress', 'member': members[0],
            'course': course.name, 'chapter': chapter.name, 'lesson': lesson.name, 'status': 'Complete'}).insert(ignore_permissions=True)
        ledger = frappe.get_doc({'doctype': 'AVO Course Access', 'account': 'mv-centr',
            'source_access_id': str(int(uuid.uuid4().hex[:10], 16)), 'source_contact_id': '999999',
            'source_course_id': '999999', 'source_snapshot_hash': 'a' * 64, 'payload_hash': 'b' * 64,
            'source_payload': '{"synthetic":true}', 'captured_at': base,
            'mapped_user': members[0], 'mapped_contact': contact.name, 'mapped_course': course.name,
            'grant': first_grant, 'enrollment': enrollments[0], 'sync_status': 'Applied'}).insert(ignore_permissions=True)
        original_source = {key: ledger.get(key) for key in ('source_access_id', 'source_contact_id', 'source_course_id',
            'source_snapshot_hash', 'payload_hash', 'source_payload', 'captured_at', 'grant')}
        frappe.set_user(staff.name); clear_policy_cache()
        removed = people.remove_student(course.name, enrollment=token)
        actual = frappe.get_doc('AVO Course Access', ledger.name)
        checks['source_immutable_after_removal'] = (all(actual.get(k) == v for k, v in original_source.items())
            and not actual.enrollment and actual.sync_status == 'Needs Review' and actual.review_reason == 'staff_removed_enrollment')
        checks['all_grants_revoked'] = removed['grants_closed'] == 2 and all(
            frappe.db.get_value('LMS Access Grant', name, 'status') == 'Revoked' for name in (first_grant, alternate.name))
        checks['enrollment_removed'] = not frappe.db.exists('LMS Enrollment', {'course': course.name, 'member': members[0]})
        checks['user_and_progress_preserved'] = bool(frappe.db.exists('User', members[0]) and frappe.db.exists('LMS Course Progress', progress.name))
        checks['course_count_updated'] = frappe.db.get_value('LMS Course', course.name, 'enrollments') == 204 and people.list_students(course.name)['total'] == 204
    except Exception:
        checks['failure_step'] = step
    finally:
        frappe.db.rollback()
        frappe.set_user(previous_user); clear_policy_cache()
        if had_release:
            frappe.conf.individual_access_release_enabled = old_release
        else:
            frappe.conf.pop('individual_access_release_enabled', None)
        if had_account:
            people.SITE_ACCOUNTS[site] = old_account
        else:
            people.SITE_ACCOUNTS.pop(site, None)
        frappe.local._lms_access_block_rows = {}
    return checks
