"""Pure decision model for individually assigned course lessons.

This experimental module consumes *already resolved* facts. It does not import AWO
records, alter enrollments, reset progress, or enforce access in Frappe. The meaning
and calculation of source fields still require evidence from each AWO configuration.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal, Mapping, Sequence


def _aware(value: datetime) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None


@dataclass(frozen=True)
class Bound:
    kind: Literal["until", "unlimited", "unknown"]
    at: datetime | None = None

    def __post_init__(self):
        if self.kind not in {"until", "unlimited", "unknown"}:
            raise ValueError("invalid bound")
        if self.kind == "until":
            if not _aware(self.at):
                raise ValueError("finite bound requires an aware datetime")
        elif self.at is not None:
            raise ValueError("non-finite bound must not carry a datetime")

    @classmethod
    def until(cls, value: datetime):
        return cls("until", value)

    @classmethod
    def unlimited(cls):
        return cls("unlimited")

    @classmethod
    def unknown(cls):
        return cls("unknown")


@dataclass(frozen=True)
class Term:
    """An explicit term; `inherit` is valid only for a personal override."""

    kind: Literal["until", "duration", "unlimited", "unknown", "inherit"]
    value: datetime | timedelta | None = None

    def __post_init__(self):
        if self.kind == "until":
            if not _aware(self.value):
                raise ValueError("date term requires an aware datetime")
        elif self.kind == "duration":
            if not isinstance(self.value, timedelta) or self.value < timedelta(0):
                raise ValueError("duration must be a non-negative timedelta")
        elif self.kind in {"unlimited", "unknown", "inherit"}:
            if self.value is not None:
                raise ValueError("term must not carry a value")
        else:
            raise ValueError("invalid term")

    @classmethod
    def until(cls, value: datetime):
        return cls("until", value)

    @classmethod
    def duration(cls, value: timedelta):
        return cls("duration", value)

    @classmethod
    def unlimited(cls):
        return cls("unlimited")

    @classmethod
    def unknown(cls):
        return cls("unknown")

    @classmethod
    def inherit(cls):
        return cls("inherit")


def resolve_term(course: Term, personal: Term, reference: datetime | None) -> Bound:
    """Apply an explicitly supplied personal override to a course term.

    Durations use the passed-in reference instant. Selecting the reference,
    calendar-boundary rules and freeze adjustments belong to a future adapter and
    must be verified against AWO; this function does not infer them.
    """
    if not isinstance(course, Term) or not isinstance(personal, Term) or course.kind == "inherit":
        raise ValueError("invalid course or personal term")
    chosen = course if personal.kind == "inherit" else personal
    if chosen.kind == "until":
        return Bound.until(chosen.value)
    if chosen.kind == "unlimited":
        return Bound.unlimited()
    if chosen.kind == "unknown" or reference is None:
        return Bound.unknown()
    if not _aware(reference):
        raise ValueError("reference must be an aware datetime")
    return Bound.until(reference.astimezone(timezone.utc) + chosen.value)


@dataclass(frozen=True)
class FreezePolicy:
    reset_progress: bool | None
    delete_homework: bool | None


@dataclass(frozen=True)
class FreezePreview:
    effects: tuple[str, ...]


def freeze_preview(policy: FreezePolicy) -> FreezePreview:
    """Describe configured consequences only; this function changes no data."""
    if not isinstance(policy, FreezePolicy):
        raise ValueError("freeze policy is required")
    if policy.reset_progress is not True and policy.reset_progress is not False:
        raise ValueError("progress behavior must be explicitly configured")
    if policy.delete_homework is not True and policy.delete_homework is not False:
        raise ValueError("homework behavior must be explicitly configured")
    effects = []
    if policy.reset_progress:
        effects.append("reset_progress")
    if policy.delete_homework:
        effects.append("delete_homework")
    return FreezePreview(tuple(effects))


def resume_deadline(deadline: Bound, frozen_at: datetime, resumed_at: datetime, *, extend: bool | None) -> Bound:
    """Apply one explicit elapsed-time freeze rule, without storing changes.

    Some courses may use another rule; the AWO adapter must establish which rule
    applies. A missing rule stays unknown rather than silently preserving/extending.
    """
    if not isinstance(deadline, Bound) or not _aware(frozen_at) or not _aware(resumed_at):
        raise ValueError("valid bound and aware freeze times are required")
    elapsed = resumed_at.astimezone(timezone.utc) - frozen_at.astimezone(timezone.utc)
    if elapsed < timedelta(0):
        raise ValueError("resume precedes freeze")
    if extend is not True and extend is not False:
        return Bound.unknown()
    if extend is False or deadline.kind != "until":
        return deadline
    return Bound.until(deadline.at.astimezone(timezone.utc) + elapsed)


@dataclass(frozen=True)
class LessonAccess:
    assigned: bool | None
    available: bool | None
    hidden: bool | None
    opens_at: datetime | None
    prerequisite_met: bool | None


@dataclass(frozen=True)
class Grant:
    student: str
    course: str
    active: bool | None
    frozen: bool | None
    starts_at: datetime | None
    ends_at: Bound
    course_ends_at: Bound
    ignore_course_end: bool | None
    lessons: Mapping[str, LessonAccess]


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str


def _bound_reason(bound: Bound, now: datetime, label: str) -> str | None:
    if not isinstance(bound, Bound) or bound.kind == "unknown":
        return "unknown_" + label
    if bound.kind == "until" and now >= bound.at.astimezone(timezone.utc):
        return "expired_" + label
    return None


def _check(grant: Grant, lesson: str, now: datetime) -> Decision:
    if grant.active is not True:
        return Decision(False, "inactive_or_unknown")
    if grant.frozen is not False:
        return Decision(False, "frozen_or_unknown")
    if not _aware(grant.starts_at):
        return Decision(False, "unknown_start")
    if now < grant.starts_at.astimezone(timezone.utc):
        return Decision(False, "not_started")
    if reason := _bound_reason(grant.ends_at, now, "personal_end"):
        return Decision(False, reason)
    if grant.ignore_course_end is not True:
        if grant.ignore_course_end is not False:
            return Decision(False, "unknown_course_end_rule")
        if reason := _bound_reason(grant.course_ends_at, now, "course_end"):
            return Decision(False, reason)

    row = grant.lessons.get(lesson)
    if not isinstance(row, LessonAccess):
        return Decision(False, "not_assigned")
    if row.assigned is not True or row.available is not True or row.hidden is not False:
        return Decision(False, "lesson_restricted_or_unknown")
    if not _aware(row.opens_at):
        return Decision(False, "unknown_opening")
    if now < row.opens_at.astimezone(timezone.utc):
        return Decision(False, "not_open_yet")
    if row.prerequisite_met is not True:
        return Decision(False, "prerequisite_or_unknown")
    return Decision(True, "allowed")


def evaluate(grants: Sequence[Grant], *, student: str, course: str, lesson: str, now: datetime) -> Decision:
    """Allow only if a matching individual grant satisfies all known conditions.

    Each grant is evaluated independently: a revoked or expired grant cannot
    negate another valid grant. End bounds use an exclusive instant; the adapter
    must derive this explicitly from the source platform's confirmed semantics.
    """
    if not _aware(now):
        raise ValueError("now must be an aware datetime")
    if not all(isinstance(value, str) and value for value in (student, course, lesson)):
        raise ValueError("student, course and lesson are required")
    now = now.astimezone(timezone.utc)
    denied = Decision(False, "no_matching_grant")
    for item in grants:
        if not isinstance(item, Grant) or item.student != student or item.course != course:
            continue
        decision = _check(item, lesson, now)
        if decision.allowed:
            return decision
        if decision.reason != "not_assigned":
            denied = decision
    return denied
