"""Pure decision model for individually assigned course lessons.

This experimental module consumes *already resolved* facts. It does not import AWO
records, alter enrollments, reset progress, or enforce access in Frappe. The meaning
and calculation of source fields still require evidence from each AWO configuration.
"""

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone, tzinfo
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
class OpeningRule:
    kind: Literal["at", "after_start", "after_previous", "unknown", "inherit"]
    value: datetime | timedelta | None = None

    def __post_init__(self):
        if self.kind == "at":
            if not _aware(self.value):
                raise ValueError("fixed opening requires an aware datetime")
        elif self.kind in {"after_start", "after_previous"}:
            if not isinstance(self.value, timedelta) or self.value < timedelta(0):
                raise ValueError("opening delay must be a non-negative timedelta")
        elif self.kind in {"unknown", "inherit"}:
            if self.value is not None:
                raise ValueError("opening rule must not carry a value")
        else:
            raise ValueError("invalid opening rule")

    @classmethod
    def at(cls, value: datetime):
        return cls("at", value)

    @classmethod
    def after_start(cls, value: timedelta):
        return cls("after_start", value)

    @classmethod
    def after_previous(cls, value: timedelta):
        return cls("after_previous", value)

    @classmethod
    def unknown(cls):
        return cls("unknown")

    @classmethod
    def inherit(cls):
        return cls("inherit")


def resolve_opening(course: OpeningRule, personal: OpeningRule, *,
                    start: datetime | None, previous: datetime | None) -> datetime | None:
    """Resolve an explicit fixed or elapsed-time opening rule.

    `previous` must already be the trusted preceding lesson's opening instant.
    This does not infer AWO's reference, calendar-day semantics, or lesson order.
    """
    if not isinstance(course, OpeningRule) or not isinstance(personal, OpeningRule) or course.kind == "inherit":
        raise ValueError("invalid course or personal opening rule")
    chosen = course if personal.kind == "inherit" else personal
    if chosen.kind == "unknown":
        return None
    if chosen.kind == "at":
        return chosen.value.astimezone(timezone.utc)
    reference = start if chosen.kind == "after_start" else previous
    if reference is None:
        return None
    if not _aware(reference):
        raise ValueError("opening reference must be an aware datetime")
    return reference.astimezone(timezone.utc) + chosen.value


@dataclass(frozen=True)
class StartRule:
    kind: Literal["immediate", "fixed", "weekly", "unknown", "inherit"]
    when: datetime | None = None
    weekday: int | None = None
    local_time: time | None = None
    zone: tzinfo | None = None
    fold: int | None = None

    def __post_init__(self):
        weekly = (self.weekday, self.local_time, self.zone, self.fold)
        if self.kind == "fixed":
            if not _aware(self.when) or any(value is not None for value in weekly):
                raise ValueError("fixed start requires only an aware instant")
        elif self.kind == "weekly":
            if (self.when is not None or type(self.weekday) is not int or self.weekday not in range(7)
                    or not isinstance(self.local_time, time) or self.local_time.tzinfo is not None
                    or not isinstance(self.zone, tzinfo) or type(self.fold) is not int or self.fold not in (0, 1)):
                raise ValueError("weekly start requires weekday, local time, timezone, and fold")
        elif self.kind in {"immediate", "unknown", "inherit"}:
            if self.when is not None or any(value is not None for value in weekly):
                raise ValueError("start rule must not carry additional values")
        else:
            raise ValueError("invalid start rule")

    @classmethod
    def immediate(cls):
        return cls("immediate")

    @classmethod
    def fixed(cls, value: datetime):
        return cls("fixed", when=value)

    @classmethod
    def weekly(cls, *, weekday: int, local_time: time, zone: tzinfo, fold: int):
        return cls("weekly", weekday=weekday, local_time=local_time, zone=zone, fold=fold)

    @classmethod
    def unknown(cls):
        return cls("unknown")

    @classmethod
    def inherit(cls):
        return cls("inherit")


def resolve_start(course: StartRule, personal: StartRule, assigned_at: datetime | None) -> datetime | None:
    """Resolve a proposed course start without assuming AWO's weekly boundary rule.

    The `weekly` variant selects the next configured local weekday/time at or after
    assignment, with an explicit fold for repeated local times. A nonexistent local
    time returns unknown. AWO's precise rule still needs source-side verification.
    """
    if not isinstance(course, StartRule) or not isinstance(personal, StartRule) or course.kind == "inherit":
        raise ValueError("invalid course or personal start rule")
    chosen = course if personal.kind == "inherit" else personal
    if chosen.kind == "unknown":
        return None
    if chosen.kind == "fixed":
        return chosen.when.astimezone(timezone.utc)
    if assigned_at is None:
        return None
    if not _aware(assigned_at):
        raise ValueError("assignment time must be an aware datetime")
    instant = assigned_at.astimezone(timezone.utc)
    if chosen.kind == "immediate":
        return instant
    local_date = instant.astimezone(chosen.zone).date()
    target_date = local_date + timedelta(days=(chosen.weekday - local_date.weekday()) % 7)

    def candidate(day):
        wall = datetime.combine(day, chosen.local_time)
        result = wall.replace(tzinfo=chosen.zone, fold=chosen.fold).astimezone(timezone.utc)
        roundtrip = result.astimezone(chosen.zone)
        return result if roundtrip.replace(tzinfo=None) == wall else None

    start = candidate(target_date)
    if start is None:
        return None
    return candidate(target_date + timedelta(days=7)) if start < instant else start


@dataclass(frozen=True)
class ClosureOptions:
    mode: Literal["close", "remove"]
    retained_lessons: tuple[str, ...]
    reset_progress: bool | None
    delete_homework: bool | None


@dataclass(frozen=True)
class ClosurePreview:
    effects: tuple[str, ...]
    course_card_action: Literal["keep", "remove"]
    retained_lessons: tuple[str, ...]


def closure_preview(policy: ClosureOptions) -> ClosurePreview:
    """Describe one requested action; this changes no data.

    This preview does not decide the final course visibility or effective access:
    other independent grants may still apply. A future server adapter must verify
    the selected lesson identifiers and reconcile all matching grants.
    """
    if not isinstance(policy, ClosureOptions):
        raise ValueError("closure options are required")
    if policy.mode not in {"close", "remove"}:
        raise ValueError("closure mode must be selected")
    if not isinstance(policy.retained_lessons, tuple) or any(
        not isinstance(item, str) or not item for item in policy.retained_lessons
    ):
        raise ValueError("retained lessons must be an explicit tuple of identifiers")
    if len(set(policy.retained_lessons)) != len(policy.retained_lessons):
        raise ValueError("duplicate retained lesson")
    if policy.mode == "remove" and policy.retained_lessons:
        raise ValueError("removed course cannot retain visible lessons in this action")
    if policy.reset_progress is not True and policy.reset_progress is not False:
        raise ValueError("progress behavior must be explicitly configured")
    if policy.delete_homework is not True and policy.delete_homework is not False:
        raise ValueError("homework behavior must be explicitly configured")
    effects = []
    if policy.reset_progress:
        effects.append("reset_progress")
    if policy.delete_homework:
        effects.append("delete_homework")
    return ClosurePreview(tuple(effects), "keep" if policy.mode == "close" else "remove", policy.retained_lessons)


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
    keep_after_personal_end: bool | None = None
    keep_after_course_end: bool | None = None
    retention_ends_at: Bound | None = None


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
    personal_end_reason = _bound_reason(grant.ends_at, now, "personal_end")
    if personal_end_reason == "unknown_personal_end":
        return Decision(False, personal_end_reason)
    course_end_reason = None
    if grant.ignore_course_end is not True:
        if grant.ignore_course_end is not False:
            return Decision(False, "unknown_course_end_rule")
        course_end_reason = _bound_reason(grant.course_ends_at, now, "course_end")
        if course_end_reason == "unknown_course_end":
            return Decision(False, course_end_reason)

    row = grant.lessons.get(lesson)
    if not isinstance(row, LessonAccess):
        return Decision(False, "not_assigned")
    if row.assigned is not True or row.available is not True or row.hidden is not False:
        return Decision(False, "lesson_restricted_or_unknown")
    if personal_end_reason and row.keep_after_personal_end is not True:
        return Decision(False, personal_end_reason)
    if course_end_reason and row.keep_after_course_end is not True:
        return Decision(False, course_end_reason)
    if personal_end_reason or course_end_reason:
        if reason := _bound_reason(row.retention_ends_at, now, "retention_end"):
            return Decision(False, reason)
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
