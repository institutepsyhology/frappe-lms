"""Rollback-only checks on the isolated stage, never production data."""
import json
import uuid
from datetime import timedelta
import frappe
from frappe.utils import now_datetime


def run():
    if frappe.local.site != 'access-stage2.local':
        raise RuntimeError('isolated_stage_required')
    from lms.lms import course_people as people
    from lms.lms.visit_tracking import record_lesson_visit
    from lms.lms.access_presentation import lesson_state, course_notice
    from lms.lms.permissions import can_access_lesson
    from lms.lms.utils import get_lesson
    old_user = frappe.session.user
    old_release = frappe.conf.get('individual_access_release_enabled')
    old_account = people.SITE_ACCOUNTS.get(frappe.local.site)
    old_data = frappe.session.get('data')
    checks = {}
    try:
        frappe.set_user('Administrator')
        people.SITE_ACCOUNTS[frappe.local.site] = 'mv-centr'
        frappe.conf.individual_access_release_enabled = True
        prefix = 'access-check-' + uuid.uuid4().hex[:10]
        student = frappe.get_doc({'doctype': 'User', 'email': prefix+'@example.invalid',
            'first_name': prefix, 'user_type': 'Website User', 'send_welcome_email': 0,
            'roles': [{'role': 'LMS Student'}]}).insert(ignore_permissions=True)
        course = frappe.get_doc({'doctype': 'LMS Course', 'title': prefix,
            'description': 'Synthetic access check', 'short_introduction': 'Synthetic',
            'published': 0, 'disable_self_learning': 1, 'instructors': [{'instructor': 'Administrator'}]}).insert(ignore_permissions=True)
        chapter = frappe.get_doc({'doctype': 'Course Chapter', 'course': course.name, 'title': prefix}).insert(ignore_permissions=True)
        frappe.get_doc({'doctype': 'Chapter Reference', 'parent': course.name, 'parenttype': 'LMS Course',
            'parentfield': 'chapters', 'chapter': chapter.name, 'idx': 1}).insert(ignore_permissions=True)
        lessons = []
        for i in range(2):
            lesson = frappe.get_doc({'doctype': 'Course Lesson', 'course': course.name, 'chapter': chapter.name,
                'title': prefix+str(i), 'content': json.dumps({'blocks':[{'type':'paragraph','data':{'text':'PRIVATE CONTENT'}}]})}).insert(ignore_permissions=True)
            lessons.append(lesson.name)
            frappe.get_doc({'doctype': 'Lesson Reference', 'parent': chapter.name, 'parenttype': 'Course Chapter',
                'parentfield': 'lessons', 'lesson': lesson.name, 'idx': i+1}).insert(ignore_permissions=True)
        frappe.get_doc({'doctype': 'LMS Enrollment', 'course': course.name, 'member': student.name,
            'member_type': 'Student'}).insert(ignore_permissions=True)
        start = now_datetime()-timedelta(days=1)
        policy = frappe.get_doc({'doctype': 'LMS Access Policy', 'course': course.name, 'enabled': 1,
            'default_personal_end_type': 'Unlimited', 'global_end_type': 'Unlimited',
            'lessons': [{'lesson': l, 'opening_type': 'After Start', 'delay_days': 0,
                'prerequisite_type': 'None'} for l in lessons]}).insert(ignore_permissions=True)
        grant = frappe.get_doc({'doctype': 'LMS Access Grant', 'course': course.name, 'member': student.name,
            'status': 'Active', 'starts_at': start, 'personal_end_type': 'Unlimited', 'course_end_type': 'Unlimited',
            'lessons': [{'lesson': l, 'opening_type': 'Inherit', 'prerequisite_state': 'Inherit'} for l in lessons]}).insert(ignore_permissions=True)
        progress = frappe.get_doc({'doctype': 'LMS Course Progress', 'course': course.name,
            'chapter': chapter.name, 'lesson': lessons[0], 'member': student.name, 'status': 'Complete'}).insert(ignore_permissions=True)
        people.change_lesson_assignments(course.name, grant.name, lessons, 0, member=student.name)
        checks['bulk_remove_keeps_progress'] = bool(frappe.db.exists('LMS Course Progress', progress.name)) and not frappe.get_doc('LMS Access Grant',grant.name).lessons
        people.change_lesson_assignments(course.name, grant.name, lessons, 1, member=student.name)
        checks['bulk_restore_and_filters'] = people.list_member_lessons(course.name, student.name, grant.name, assignment_filter='assigned')['total']==2 and people.list_member_lessons(course.name, student.name, grant.name, assignment_filter='available')['total']==0
        people.set_member_block(course.name,1,member=student.name)
        checks['hard_block_wins'] = not lesson_state(course.name,lessons[0],student.name)['available']
        people.set_member_block(course.name,0,member=student.name)
        frappe.set_user(student.name)
        frappe.session.data = frappe._dict(impersonated_by='Administrator')
        checks['staff_does_not_create_visit'] = not record_lesson_visit(course.name,lessons[0])['recorded'] and not frappe.db.exists('LMS Lesson Visit',{'member':student.name,'lesson':lessons[0]})
        frappe.session.data = frappe._dict()
        checks['learner_creates_verified_visit'] = record_lesson_visit(course.name,lessons[0])['recorded'] and bool(frappe.db.get_value('LMS Lesson Visit',{'member':student.name,'lesson':lessons[0]},'first_learner_visit_at'))
        checks['free_order_available'] = can_access_lesson(lessons[1])
        frappe.set_user('Administrator')
        frappe.db.set_value('LMS Access Grant', grant.name, {'personal_end_type':'At','ends_at':now_datetime()-timedelta(hours=1),'completed_retention_type':'Unlimited'})
        checks['completed_retention_after_expiry'] = can_access_lesson(lessons[0],user=student.name) and not can_access_lesson(lessons[1],user=student.name)
        return checks
    finally:
        frappe.db.rollback()
        frappe.set_user(old_user)
        frappe.session.data = old_data
        frappe.conf.individual_access_release_enabled = old_release
        if old_account is None: people.SITE_ACCOUNTS.pop(frappe.local.site,None)
        else: people.SITE_ACCOUNTS[frappe.local.site] = old_account
        frappe.local._lms_access_block_rows = {}
