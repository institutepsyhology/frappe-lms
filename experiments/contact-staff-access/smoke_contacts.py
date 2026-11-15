"""Actual-controller contact checks on access-stage2.local only.

Call run() inside an already initialized isolated stage request. Fixtures are
rolled back, no login/password/email operations are performed, and the result
contains booleans/counts only. The contact API chooses its own internal key;
all supplied person identifiers use the synthetic smoke prefix.
"""
import frappe


SITE = 'access-stage2.local'


def _check(value, code):
    if not value:
        raise RuntimeError(code)


def _denied(operation, code):
    try:
        operation()
    except frappe.PermissionError:
        return True
    raise RuntimeError(code)


def run():
    _check(getattr(frappe.local, 'site', None) == SITE, 'contact_smoke_wrong_site')
    from lms.lms import avo_contact_card as legacy
    from lms.lms import contact_workspace as workspace
    from lms.lms.staff_policy import clear_policy_cache

    previous_user = frappe.session.user
    prefix = 'contact-staff-smoke-' + frappe.generate_hash(length=8)
    student = prefix + '-person@example.invalid'
    reader = prefix + '-reader@example.invalid'
    fixture_names = []
    report = {}
    try:
        frappe.set_user('Administrator')
        clear_policy_cache()
        _check(all(frappe.get_meta('Contact').has_field(field) for field in
                   ('custom_avo_telegram_id', 'custom_avo_telegram_username', 'custom_avo_contact_id', 'custom_avo_account')),
               'contact_smoke_source_fields_missing')
        for name, label in ((student, prefix + '-person'), (reader, prefix + '-reader')):
            _check(not frappe.db.exists('User', name), 'contact_smoke_fixture_collision')
            frappe.get_doc({'doctype': 'User', 'email': name, 'first_name': label,
                'username': label, 'send_welcome_email': 0, 'user_type': 'Website User',
                'roles': [{'role': 'LMS Student'}]}).insert(ignore_permissions=True)

        before_users = frappe.db.count('User')
        social = workspace.create_contact({'email': '', 'custom_avo_telegram_id': '900000000001',
                                           'custom_avo_telegram_username': prefix + '-social'})
        _check(social.get('kind') == 'Contact', 'contact_smoke_created_login_instead_of_contact')
        fixture_names.append(social['name'])
        social_doc = frappe.get_doc('Contact', social['name'])
        _check(not social_doc.get('first_name') and not social_doc.get('last_name')
               and not social_doc.get('email_ids') and not social_doc.get('email_id') and not social_doc.get('user'),
               'contact_smoke_social_contact_received_invented_identity')
        _check(frappe.db.count('User') == before_users, 'contact_smoke_contact_created_user')
        report['social_only_contact_no_fake_identity'] = True

        # A structural phone placeholder must survive the actual Contact child
        # table and controller. It is not treated as a unique person identity.
        fake_phone = '79999999999'
        phone = workspace.create_contact({'first_name': prefix + '-phone', 'mobile_no': fake_phone})
        fixture_names.append(phone['name'])
        saved_phone = workspace.save_card('Contact', phone['name'], {'mobile_no': fake_phone})
        phone_doc = frappe.get_doc('Contact', phone['name'])
        _check(saved_phone.get('mobile_no') == fake_phone and any(
            row.phone == fake_phone and row.is_primary_mobile_no for row in phone_doc.phone_nos),
            'contact_smoke_placeholder_phone_not_persisted')
        report['contact_placeholder_phone_persisted'] = True

        # Exercise reload-and-save too: the insert's mandatory-field flag is
        # not assumed to remain on a freshly loaded social-only Contact.
        social_saved = workspace.save_card('Contact', social['name'],
            {'mobile_no': fake_phone, 'custom_no_marketing_email': False})
        social_reloaded = frappe.get_doc('Contact', social['name'])
        _check(not social_reloaded.get('first_name') and not social_reloaded.get('email_ids')
               and social_saved.get('mobile_no') == fake_phone,
               'contact_smoke_social_only_reload_save_failed')
        report['social_only_reload_save'] = True

        native_saved = workspace.save_card('User', student,
            {'last_name': 'Synthetic', 'mobile_no': fake_phone})
        _check(native_saved.get('kind') == 'User' and native_saved.get('mobile_no') == fake_phone,
               'contact_smoke_user_save_failed')
        report['user_placeholder_phone_persisted'] = True
        _check(legacy.get_card('User', student)['name'] == workspace.get_card('User', student)['name'],
               'contact_smoke_legacy_user_card_differs')
        _check(legacy.get_card('Contact', phone['name'])['name'] == phone['name'],
               'contact_smoke_legacy_contact_card_differs')
        report['both_card_kinds_same_service'] = True

        # Exercise the real MariaDB UNION, filtering and numeric bounds; do not
        # print or return any rows, names, email addresses or contact payloads.
        listing = workspace.list_people(page=1, page_size=50, search=prefix, sort='email', direction='desc')
        _check(any(row.kind == 'User' and row.name == student for row in listing['rows']),
               'contact_smoke_union_user_missing')
        _check(any(row.kind == 'Contact' and row.name == phone['name'] for row in listing['rows']),
               'contact_smoke_union_contact_missing')
        _check(listing['page_size'] == 50 and len(listing['rows']) <= 50,
               'contact_smoke_pagination_unbounded')
        second = workspace.list_people(page=2, page_size=25, search=prefix, sort='full_name', direction='asc')
        _check(second['page'] == 2 and len(second['rows']) <= 25 and second['total'] == listing['total'],
               'contact_smoke_second_page_invalid')
        report.update(mariadb_union_both_kinds=True, paged_contact_rows=len(listing['rows']), pagination_bounded=True)

        position = frappe.get_doc({'doctype': 'LMS Staff Position', 'title': prefix + '-read-only',
            'active': 1, 'course_scope': 'All',
            'permissions': [{'resource': 'contacts', 'action': 'read'}],
            'native_roles': [{'role': 'LMS Student'}]}).insert(ignore_permissions=True)
        frappe.get_doc({'doctype': 'LMS Staff Assignment', 'user': reader,
                        'position': position.name, 'active': 1}).insert(ignore_permissions=True)
        frappe.set_user(reader)
        clear_policy_cache()
        readonly = workspace.get_card('Contact', social['name'])
        _check(readonly['capabilities']['read'] and not readonly['capabilities']['write']
               and not any(readonly['capabilities'].get('credential_' + action) for action in ('read', 'write', 'send')),
               'contact_smoke_read_only_caps_invalid')
        _check(workspace.list_people(page=1, page_size=50, search=prefix)['rows'],
               'contact_smoke_reader_list_denied')
        report['read_only_position_can_read_contact_and_list'] = True
        report['read_only_position_cannot_save'] = _denied(
            lambda: workspace.save_card('Contact', social['name'], {'first_name': 'Forbidden'}),
            'contact_smoke_read_only_write_allowed')
        report['read_only_position_cannot_create'] = _denied(
            lambda: workspace.create_contact({'first_name': prefix + '-forbidden'}),
            'contact_smoke_read_only_create_allowed')
        report['legacy_save_cannot_bypass_position'] = _denied(
            lambda: legacy.save_card('Contact', social['name'], {'first_name': 'Forbidden'}),
            'contact_smoke_legacy_write_bypass')
        # This must fail at authorization, before any email operation can run.
        report['contact_read_does_not_send_password_reset'] = _denied(
            lambda: legacy.send_password_reset(student), 'contact_smoke_reset_permission_bypass')
    finally:
        frappe.db.rollback()
        clear_policy_cache()
        frappe.set_user(previous_user)
        for name in (student, reader):
            frappe.clear_cache(user=name)

    _check(not any(frappe.db.exists('User', name) for name in (student, reader))
           and not any(frappe.db.exists('Contact', name) for name in fixture_names),
           'contact_smoke_fixture_rollback_failed')
    report['rolled_back'] = True
    return report
