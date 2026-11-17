"""Add only access presentation settings and verified visit dates."""
import frappe


def apply_schema():
    for doctype in ('lms_course', 'course_lesson', 'lms_lesson_visit'):
        frappe.reload_doc('lms', 'doctype', doctype, force=True)
    for doctype, fields in {
        'LMS Course': ('show_when_unavailable', 'access_notice_content'),
        'Course Lesson': ('show_when_unavailable', 'access_notice_content'),
        'LMS Lesson Visit': ('first_learner_visit_at', 'last_learner_visit_at'),
    }.items():
        if not all(frappe.get_meta(doctype).has_field(name) for name in fields):
            raise RuntimeError('access_schema_incomplete')
    frappe.db.commit()
    frappe.clear_cache()
    return {'additive_schema_verified': True, 'historical_visits_backfilled': False}
