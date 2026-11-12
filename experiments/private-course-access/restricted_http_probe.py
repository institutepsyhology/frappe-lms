"""Prove a member can open an allowed lesson but not another lesson in that course.

Trusted, explicitly invoked bench operator. Supply identities privately; returned
results contain booleans only. Reuses the reviewed temporary-session transport.
"""
from http_probe import SITE, _ordinary, _state, no_material, request, temporary_session, visible_as_expected


def run_restricted_lesson(fr, *, site, member, course_id, allowed_lesson_id, denied_lesson_id):
    from lms.lms.avo_course_routes import _position
    from lms.lms.individual_access import grant_allows_lesson, policy_applies

    if site != SITE or fr.local.site != site or fr.session.user != "Administrator":
        raise RuntimeError("trusted_site_administrator_required")
    if fr.conf.get("deny_multiple_sessions") or fr.db.get_system_setting("deny_multiple_sessions"):
        raise RuntimeError("probe_would_clear_existing_sessions")
    if str(allowed_lesson_id) == str(denied_lesson_id):
        raise RuntimeError("distinct_lesson_ids_required")
    courses = fr.get_all("LMS Course", filters={"custom_avo_account": "mv-centr", "custom_avo_id": str(course_id)},
                         fields=["name", "published", "disable_self_learning"], limit_page_length=2)
    if len(courses) != 1:
        raise RuntimeError("ambiguous_course_identity")
    course = courses[0]
    if course.published or not course.disable_self_learning or not policy_applies(course.name):
        raise RuntimeError("private_course_policy_required")
    if not _ordinary(fr, member, course.name, True):
        raise RuntimeError("ordinary_enrolled_member_required")
    lessons = {}
    for label, source_id in (("allowed", allowed_lesson_id), ("denied", denied_lesson_id)):
        rows = fr.get_all("Course Lesson", filters={"custom_avo_account": "mv-centr", "custom_avo_id": str(source_id)},
                          fields=["name", "course", "chapter", "is_draft", "include_in_preview", "publication_audience"], limit_page_length=2)
        if len(rows) != 1 or rows[0].course != course.name:
            raise RuntimeError("ambiguous_lesson_identity")
        lesson = rows[0]
        # A denied draft would not prove that the personal allowlist is enforced.
        if lesson.is_draft or lesson.include_in_preview or lesson.publication_audience != "All":
            raise RuntimeError("both_lessons_must_be_released_without_preview")
        position = _position(course.name, lesson.name, lesson.chapter)
        if not position:
            raise RuntimeError("ambiguous_lesson_position")
        lessons[label] = (str(source_id), lesson, position)
    decisions = {label: bool(grant_allows_lesson(user=member, lesson=value[1].name))
                 for label, value in lessons.items()}
    if decisions != {"allowed": True, "denied": False}:
        raise RuntimeError("expected_personal_allowlist_decisions_required")
    baseline = _state(fr, [member], course.name)
    results = {"native_allowlist_separates_lessons": True}
    try:
        with temporary_session(fr, member, site) as cookie:
            for label, (source_id, lesson, position) in lessons.items():
                allowed = label == "allowed"
                checks = {}
                for key, method, args in (
                    ("source_lesson", "lms.lms.avo_course_routes.get_lesson_by_source",
                     {"course_id": str(course_id), "lesson_id": source_id}),
                    ("direct_lesson", "lms.lms.utils.get_lesson",
                     {"course": course.name, "chapter": position[0], "lesson": position[1]}),
                ):
                    status, data = request(site, "/api/method/" + method, args, cookie)
                    value = data.get("message") if isinstance(data, dict) else None
                    visible = isinstance(value, dict) and value.get("name") == lesson.name and not (value.get("locked") or value.get("no_preview"))
                    checks[key] = visible_as_expected(status, visible, allowed) and (allowed or no_material(value))
                    checks[key + "_instructor_fields_hidden"] = not isinstance(value, dict) or not (value.get("instructor_content") or value.get("instructor_notes"))
                status, data = request(site, "/api/method/lms.lms.avo_course_routes.resolve",
                                       {"course_id": str(course_id), "lesson_id": source_id}, cookie)
                value = data.get("message") if isinstance(data, dict) else None
                checks["stable_route"] = visible_as_expected(status, isinstance(value, dict) and value.get("lesson_name") == lesson.name, allowed) and (allowed or value in (None, {}))
                results[label] = checks
    finally:
        results["learner_state_unchanged"] = _state(fr, [member], course.name) == baseline
    results["ok"] = all(all(value.values()) if isinstance(value, dict) else value for value in results.values())
    return results
