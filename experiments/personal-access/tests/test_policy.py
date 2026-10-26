import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone, tzinfo

from personal_access.policy import (
    Bound, FreezePolicy, Grant, LessonAccess, Term, evaluate, freeze_preview,
    resolve_term, resume_deadline,
)


NOW = datetime(2026, 10, 27, 12, tzinfo=timezone.utc)


def grant(**changes):
    base = Grant(
        student="student-a",
        course="course-a",
        active=True,
        frozen=False,
        starts_at=NOW - timedelta(days=1),
        ends_at=Bound.unlimited(),
        course_ends_at=Bound.unlimited(),
        ignore_course_end=False,
        lessons={
            "lesson-1": LessonAccess(
                assigned=True,
                available=True,
                hidden=False,
                opens_at=NOW - timedelta(days=1),
                prerequisite_met=True,
            )
        },
    )
    return replace(base, **changes)


def lesson(**changes):
    return replace(grant().lessons["lesson-1"], **changes)


class IndividualAccessTests(unittest.TestCase):
    def check(self, grants, student="student-a", course="course-a", target="lesson-1"):
        return evaluate(grants, student=student, course=course, lesson=target, now=NOW)

    def test_student_must_have_specific_lesson_for_specific_course(self):
        g = grant()
        self.assertTrue(self.check([g]).allowed)
        self.assertFalse(self.check([g], student="student-b").allowed)
        self.assertFalse(self.check([g], course="course-b").allowed)
        self.assertFalse(self.check([g], target="lesson-2").allowed)

    def test_independent_course_and_lesson_flags(self):
        for field, value in (("assigned", False), ("available", False), ("hidden", True),
                             ("assigned", None), ("available", None), ("hidden", None)):
            with self.subTest(field=field, value=value):
                result = self.check([grant(lessons={"lesson-1": lesson(**{field: value})})])
                self.assertFalse(result.allowed)

    def test_live_time_bounds_are_checked_on_each_request(self):
        g = grant(starts_at=NOW, ends_at=Bound.until(NOW + timedelta(seconds=1)))
        self.assertTrue(self.check([g]).allowed)
        self.assertFalse(evaluate([g], student="student-a", course="course-a", lesson="lesson-1",
                                  now=NOW + timedelta(seconds=1)).allowed)
        self.assertFalse(self.check([replace(g, starts_at=NOW + timedelta(seconds=1))]).allowed)

    def test_known_course_deadline_limits_personal_unlimited(self):
        g = grant(course_ends_at=Bound.until(NOW))
        self.assertFalse(self.check([g]).allowed)
        self.assertTrue(self.check([replace(g, ignore_course_end=True)]).allowed)

    def test_earlier_personal_deadline_still_applies_when_ignoring_course_end(self):
        g = grant(ends_at=Bound.until(NOW), ignore_course_end=True)
        self.assertFalse(self.check([g]).allowed)

    def test_unknown_relevant_facts_never_create_access(self):
        cases = [grant(active=None), grant(frozen=None), grant(starts_at=None),
                 grant(ends_at=Bound.unknown()), grant(ignore_course_end=None),
                 grant(course_ends_at=Bound.unknown()),
                 grant(lessons={"lesson-1": lesson(opens_at=None)}),
                 grant(lessons={"lesson-1": lesson(prerequisite_met=None)})]
        for g in cases:
            with self.subTest(g=g):
                self.assertFalse(self.check([g]).allowed)

    def test_ignored_course_end_need_not_be_known(self):
        self.assertTrue(self.check([grant(ignore_course_end=True, course_ends_at=Bound.unknown())]).allowed)

    def test_scheduled_lesson_and_stop_lesson(self):
        later = grant(lessons={"lesson-1": lesson(opens_at=NOW + timedelta(seconds=1))})
        blocked = grant(lessons={"lesson-1": lesson(prerequisite_met=False)})
        self.assertFalse(self.check([later]).allowed)
        self.assertFalse(self.check([blocked]).allowed)
        self.assertTrue(self.check([replace(later, lessons={"lesson-1": lesson(opens_at=NOW)})]).allowed)

    def test_revoked_frozen_and_multiple_independent_grants(self):
        good = grant()
        revoked = replace(good, active=False)
        frozen = replace(good, frozen=True)
        self.assertFalse(self.check([revoked, frozen]).allowed)
        self.assertTrue(self.check([revoked, frozen, good]).allowed)

    def test_end_must_be_timezone_aware_and_finite(self):
        with self.assertRaises(ValueError):
            Bound.until(datetime(2026, 10, 27, 12))
        with self.assertRaises(ValueError):
            evaluate([grant()], student="student-a", course="course-a", lesson="lesson-1",
                     now=datetime(2026, 10, 27, 12))

    def test_invalid_boolean_does_not_become_true_by_python_truthiness(self):
        for bad in ("1", 1, [], object()):
            with self.subTest(bad=repr(bad)):
                self.assertFalse(self.check([grant(active=bad)]).allowed)

    def test_no_grants_denies_and_does_not_expose_other_students(self):
        self.assertFalse(self.check([]).allowed)
        a = self.check([grant(student="other")])
        b = self.check([])
        self.assertEqual(a, b)

    def test_opening_unknown_must_not_be_treated_as_zero_day(self):
        g = grant(lessons={"lesson-1": lesson(opens_at=None)})
        self.assertFalse(self.check([g]).allowed)

    def test_course_term_can_be_overridden_per_student(self):
        default = Term.duration(timedelta(days=30))
        self.assertEqual(resolve_term(default, Term.inherit(), NOW), Bound.until(NOW + timedelta(days=30)))
        self.assertEqual(resolve_term(default, Term.until(NOW + timedelta(days=2)), NOW),
                         Bound.until(NOW + timedelta(days=2)))
        self.assertEqual(resolve_term(default, Term.unlimited(), NOW), Bound.unlimited())

    def test_duration_without_known_start_is_unknown(self):
        self.assertEqual(resolve_term(Term.duration(timedelta(days=30)), Term.inherit(), None), Bound.unknown())
        self.assertEqual(resolve_term(Term.unknown(), Term.inherit(), NOW), Bound.unknown())

    def test_invalid_duration_is_rejected(self):
        with self.assertRaises(ValueError):
            Term.duration(timedelta(days=-1))

    def test_freeze_duration_is_an_explicit_per_course_choice(self):
        end = Bound.until(NOW + timedelta(days=30))
        start, finish = NOW, NOW + timedelta(days=5)
        self.assertEqual(resume_deadline(end, start, finish, extend=True),
                         Bound.until(NOW + timedelta(days=35)))
        self.assertEqual(resume_deadline(end, start, finish, extend=False), end)
        self.assertEqual(resume_deadline(Bound.unlimited(), start, finish, extend=True), Bound.unlimited())
        self.assertEqual(resume_deadline(Bound.unknown(), start, finish, extend=True), Bound.unknown())

    def test_unknown_or_invalid_freeze_does_not_invent_an_end_date(self):
        self.assertEqual(resume_deadline(Bound.until(NOW), NOW, NOW, extend=None), Bound.unknown())
        with self.assertRaises(ValueError):
            resume_deadline(Bound.until(NOW), NOW, NOW - timedelta(seconds=1), extend=True)

    def test_freeze_can_preview_preservation_or_deletion_without_mutating_data(self):
        kept = freeze_preview(FreezePolicy(reset_progress=False, delete_homework=False))
        reset = freeze_preview(FreezePolicy(reset_progress=True, delete_homework=True))
        self.assertEqual(kept.effects, ())
        self.assertEqual(reset.effects, ("reset_progress", "delete_homework"))
        with self.assertRaises(ValueError):
            freeze_preview(FreezePolicy(reset_progress=None, delete_homework=False))

    def test_ambiguous_local_clock_does_not_open_lesson_an_hour_early(self):
        class FoldZone(tzinfo):
            def utcoffset(self, value):
                return timedelta(hours=1 if value.fold == 0 else 0)

            def dst(self, value):
                return timedelta(0)

        zone = FoldZone()
        first = datetime(2026, 10, 25, 1, 30, tzinfo=zone, fold=0)
        second = datetime(2026, 10, 25, 1, 30, tzinfo=zone, fold=1)
        g = grant(starts_at=second, lessons={"lesson-1": lesson(opens_at=first)})
        result = evaluate([g], student="student-a", course="course-a", lesson="lesson-1", now=first)
        self.assertFalse(result.allowed)

    def test_expiration_checks_instant_not_repeated_local_clock(self):
        class FoldZone(tzinfo):
            def utcoffset(self, value):
                return timedelta(hours=1 if value.fold == 0 else 0)

            def dst(self, value):
                return timedelta(0)

        zone = FoldZone()
        first = datetime(2026, 10, 25, 1, 30, tzinfo=zone, fold=0)
        second = datetime(2026, 10, 25, 1, 30, tzinfo=zone, fold=1)
        g = grant(starts_at=first - timedelta(days=1), ends_at=Bound.until(second),
                  lessons={"lesson-1": lesson(opens_at=first - timedelta(days=1))})
        result = evaluate([g], student="student-a", course="course-a", lesson="lesson-1", now=first)
        self.assertTrue(result.allowed)


if __name__ == "__main__":
    unittest.main()
