"""Trusted MVC operator: release staging drafts without changing personal grants.

The public publish_lesson(All) action deliberately adds lesson assignments to
other grants. This migration must preserve the archived allowlists, so it uses
the controller's publication flag on each verified lesson instead.
"""
import hashlib
import json
from pathlib import Path
import sys

SIBLING = Path(__file__).resolve().parents[1] / 'avo-access-sync'
if SIBLING.is_dir():
    sys.path.insert(0, str(SIBLING))
import activation

target = activation.target
ACCOUNT = 'mv-centr'

BASE = """FROM `tabAVO Course Access` a
 JOIN `tabLMS Access Grant` g ON g.name=a.grant AND g.status='Active'
 JOIN `tabLMS Enrollment` e ON e.name=a.enrollment
 JOIN `tabUser` u ON u.name=g.member
 JOIN `tabLMS Course` c ON c.name=g.course
 WHERE a.account=%s AND a.sync_status='Applied'"""
PARENT_AUDIT_BASE = BASE.replace("JOIN `tabLMS Access Grant` g ON g.name=a.grant AND g.status='Active'",
    "LEFT JOIN `tabLMS Access Grant` g ON g.name=a.grant").replace(
    ' JOIN `tabLMS Enrollment`', ' LEFT JOIN `tabLMS Enrollment`').replace(
    ' JOIN `tabUser`', ' LEFT JOIN `tabUser`').replace(' JOIN `tabLMS Course`', ' LEFT JOIN `tabLMS Course`')
BAD_PARENT_SQL = """SELECT COUNT(*) AS n """ + PARENT_AUDIT_BASE + """
 AND (g.name IS NULL OR e.name IS NULL OR u.name IS NULL OR c.name IS NULL
  OR COALESCE(a.mapped_user,'')<>g.member OR COALESCE(a.mapped_course,'')<>g.course
  OR e.member<>g.member OR e.course<>g.course
  OR COALESCE(u.custom_avo_account,'')<>a.account
  OR COALESCE(u.custom_avo_contact_id,'')<>COALESCE(a.source_contact_id,'')
  OR COALESCE(c.custom_avo_account,'')<>a.account
  OR COALESCE(c.custom_avo_id,'')<>COALESCE(a.source_course_id,'')
  OR g.name<>CONCAT('avo-mv-centr-grant-',COALESCE(a.source_access_id,''))
  OR e.name<>CONCAT('avo-mv-centr-enrollment-',COALESCE(a.source_contact_id,''),'-',COALESCE(a.source_course_id,'')))"""
CHILD_BASE = BASE.replace(' WHERE', """
 JOIN `tabLMS Access Grant Lesson` gl ON gl.parent=g.name
 WHERE""")
BAD_CHILD_SQL = "SELECT COUNT(*) AS n " + CHILD_BASE + """
 AND (gl.parenttype<>'LMS Access Grant' OR gl.parentfield<>'lessons'
  OR NOT EXISTS (SELECT 1 FROM `tabCourse Lesson` l WHERE l.name=gl.lesson
    AND l.course=g.course AND l.custom_avo_account=a.account
    AND l.custom_avo_id IS NOT NULL AND l.custom_avo_id<>''))"""
CANDIDATE_SQL = """SELECT DISTINCT l.name,l.course,l.custom_avo_id,l.custom_avo_account,
 l.is_draft,l.publication_audience,l.lesson_published_at,l.include_in_preview
 """ + CHILD_BASE.replace(' WHERE', " JOIN `tabCourse Lesson` l ON l.name=gl.lesson WHERE")
SIGNATURE_SQL = """SELECT
 (SELECT COUNT(*) FROM `tabLMS Access Grant` WHERE name LIKE 'avo-mv-centr-grant-%%') AS grants,
 (SELECT COUNT(*) FROM `tabLMS Enrollment` WHERE name LIKE 'avo-mv-centr-enrollment-%%') AS enrollments,
 (SELECT COALESCE(SUM(CRC32(CONCAT_WS('|',name,member,course,
  role,member_type))),0) FROM `tabLMS Enrollment`
  WHERE name LIKE 'avo-mv-centr-enrollment-%%') AS enrollment_crc,
 COUNT(*) AS lesson_rows,
 COALESCE(SUM(CRC32(CONCAT_WS('|',gl.name,gl.parent,gl.parenttype,gl.parentfield,gl.idx,
 gl.lesson,gl.opening_type,gl.opens_at,gl.delay_days,gl.prerequisite_state,gl.manual_open,
 gl.retain_when_limited,gl.retention_end_type,gl.retention_ends_at))),0) AS lesson_crc,
 COALESCE(SUM(CRC32(CONCAT_WS('|',g.name,g.member,g.course,g.status,g.frozen_at,g.starts_at,
 g.personal_end_type,g.ends_at,g.personal_end_days,g.course_end_type,g.course_ends_at,
 g.ignore_course_end,g.completed_retention_type,g.completed_retention_days,
 g.visited_retention_type,g.visited_retention_days))),0) AS grant_crc
 FROM `tabLMS Access Grant` g JOIN `tabLMS Access Grant Lesson` gl ON gl.parent=g.name
 WHERE g.name LIKE 'avo-mv-centr-grant-%%'"""
LESSON_FIXED = ('title', 'content', 'instructor_content', 'body', 'course', 'chapter',
                'custom_avo_account', 'custom_avo_id', 'custom_lms_id')
COURSE_FIXED = ('title', 'short_introduction', 'description', 'custom_avo_account',
                'custom_avo_id', 'custom_lms_id', 'published')
LESSON_FLAGS = ('is_draft', 'publication_audience', 'lesson_published_at', 'include_in_preview')


def _require(fr):
    target._require(fr)
    if fr.conf.get('individual_access_release_enabled') is not True:
        raise target.Rejected('individual_access_release_disabled')
    if fr.db.get_single_value('System Settings', 'time_zone') != 'Europe/Moscow':
        raise target.Rejected('unexpected_site_timezone')


def _signature(fr):
    rows = fr.db.sql(SIGNATURE_SQL, as_dict=True)
    if len(rows) != 1:
        raise target.Rejected('invalid_grant_signature')
    return {key: str(rows[0].get(key)) for key in
            ('grants', 'enrollments', 'enrollment_crc', 'lesson_rows', 'lesson_crc', 'grant_crc')}


def _fixed(doc, fields):
    value = {key: doc.get(key) for key in fields}
    raw = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(',', ':'), default=str)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def _flags(doc, fields):
    return {key: (doc.get(key).isoformat(sep=' ') if hasattr(doc.get(key), 'isoformat')
                  else doc.get(key)) for key in fields}


def plan(fr, *, known_source_draft_ids=()):
    """Read-only plan; no content, user names, addresses or credentials returned."""
    _require(fr)
    excluded = activation._excluded(known_source_draft_ids)
    courses = fr.get_all('LMS Course', filters={'custom_avo_account': ACCOUNT},
        fields=['name', 'custom_avo_account', 'custom_avo_id', 'published', 'disable_self_learning'],
        limit_page_length=0)
    by_name, source_ids = {}, set()
    for row in courses:
        if (row.get('custom_avo_account') != ACCOUNT or not target._id(row.get('custom_avo_id'))
                or row.get('name') in by_name or row.get('custom_avo_id') in source_ids
                or row.get('published') != 0
                or row.get('disable_self_learning') not in (0, 1)):
            raise target.Rejected('unexpected_imported_course')
        by_name[row['name']] = row
        source_ids.add(row['custom_avo_id'])
    if not courses:
        raise target.Rejected('no_imported_courses')
    for query in (BAD_PARENT_SQL, BAD_CHILD_SQL):
        values = fr.db.sql(query, (ACCOUNT,), as_dict=True)
        if len(values) != 1 or int(values[0].get('n', -1)) != 0:
            raise target.Rejected('invalid_owned_access_reference')
    lessons, seen, checked_courses, held_drafts = [], set(), set(), 0
    for row in fr.db.sql(CANDIDATE_SQL, (ACCOUNT,), as_dict=True):
        if (row.get('course') not in by_name or row.get('name') in seen
                or row.get('custom_avo_account') != ACCOUNT or not target._id(row.get('custom_avo_id'))
                or row.get('is_draft') not in (0, 1) or row.get('include_in_preview') not in (0, 1)):
            raise target.Rejected('unexpected_candidate_lesson')
        seen.add(row['name'])
        if row['custom_avo_id'] in excluded:
            held_drafts += 1
            continue
        course = by_name[row['course']]
        if row['course'] not in checked_courses:
            activation._policy(fr, row['course'], course['custom_avo_id'], verify_only=True)
            checked_courses.add(row['course'])
        if not row['is_draft'] and row.get('publication_audience') not in (None, '', 'All'):
            raise target.Rejected('unexpected_existing_publication_audience')
        lessons.append(dict(row))
    return {'courses': courses, 'lessons': lessons, 'grant_signature': _signature(fr),
            'summary': {'imported_courses': len(courses), 'referenced_lessons': len(seen),
                        'held_source_drafts': held_drafts,
                        'courses_to_disable_self_learning': sum(not row['disable_self_learning'] for row in courses),
                        'lessons_to_enable': sum(row['is_draft'] or row['include_in_preview']
                                                 for row in lessons)}}


def apply(fr, journal_callback, *, limit=None, known_source_draft_ids=()):
    """Apply verified course settings and lesson staging flags, preserving grants."""
    if not callable(journal_callback):
        raise target.Rejected('journal_callback_required')
    if limit is not None and (type(limit) is not int or limit < 1):
        raise target.Rejected('invalid_limit')
    prepared = plan(fr, known_source_draft_ids=known_source_draft_ids)
    changed_courses = changed_lessons = 0

    def save_one(doctype, row, fields, fixed_fields, values):
        committed = False
        fr.db.begin()
        try:
            doc = fr.get_doc(doctype, row['name'], for_update=True)
            if (doc.get('custom_avo_account') != ACCOUNT
                    or doc.get('custom_avo_id') != row['custom_avo_id']
                    or (doctype == 'Course Lesson' and doc.get('course') != row['course'])):
                raise target.Rejected('source_identity_changed')
            if doctype == 'LMS Course' and doc.get('published') != 0:
                raise target.Rejected('course_publication_changed')
            before, fixed = _flags(doc, fields), _fixed(doc, fixed_fields)
            if doctype == 'Course Lesson':
                activation._policy(fr, doc.get('course'),
                    next(course['custom_avo_id'] for course in prepared['courses']
                         if course['name'] == doc.get('course')), verify_only=True)
                if doc.get('is_draft') != row['is_draft'] or doc.get('publication_audience') != row.get('publication_audience'):
                    raise target.Rejected('lesson_publication_changed')
                doc.flags.lesson_publication_action = True
                if not doc.get('lesson_published_at'):
                    values = {**values, 'lesson_published_at': fr.utils.now_datetime()}
            event = {'doctype': doctype, 'name': row['name'], 'source_id': row['custom_avo_id'], 'before': before}
            journal_callback({'event': 'before', **event})
            doc.update(values)
            doc.save()
            saved = fr.get_doc(doctype, row['name'])
            if _fixed(saved, fixed_fields) != fixed or any(saved.get(key) != value for key, value in values.items()):
                raise target.Rejected('publication_readback_mismatch')
            after = _flags(saved, fields)
            journal_callback({'event': 'verified_uncommitted', **event, 'after': after})
            fr.db.commit(); committed = True
            journal_callback({'event': 'committed', **event, 'after': after})
        except Exception as exc:
            fr.db.rollback()
            if committed:
                raise target.Rejected('journal_write_outcome_unknown') from None
            if isinstance(exc, target.Rejected): raise
            raise target.Rejected('publication_write_failed') from None

    for row in prepared['courses']:
        if not row['disable_self_learning']:
            save_one('LMS Course', row, ('published', 'disable_self_learning'), COURSE_FIXED,
                     {'disable_self_learning': 1})
            changed_courses += 1
    for row in prepared['lessons']:
        if not row['is_draft'] and not row['include_in_preview']:
            continue
        if limit is not None and changed_lessons >= limit:
            break
        save_one('Course Lesson', row, LESSON_FLAGS, LESSON_FIXED,
                 {'is_draft': 0, 'publication_audience': 'All', 'include_in_preview': 0})
        changed_lessons += 1
    if _signature(fr) != prepared['grant_signature']:
        raise target.Rejected('personal_access_changed_during_publication')
    return {**prepared['summary'], 'changed_courses': changed_courses, 'changed_lessons': changed_lessons,
            'personal_access_unchanged': True, 'course_publication_unchanged': True,
            'limited_run': limit is not None}
