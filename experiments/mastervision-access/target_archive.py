"""Read a complete, origin-bound MV lesson-access archive without modifying it."""
from contextlib import closing, contextmanager
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import zlib


ACCOUNT = "mastervision"
ORIGIN = "https://shop.mastervision.su"
BOUND = 446858
CONTROL_COURSE = 598
EXPIRED_CONTROL = 446462
FIVE_CONTROL = 446809
FIVE_LESSONS = (6518, 9251, 9252, 9253, 9254)
MOSCOW = timezone(timedelta(hours=3))


class Review(ValueError):
    """Reason code only; do not place personal source data in logs."""


def require(condition, code):
    if not condition:
        raise Review(code)


def instant(value):
    require(isinstance(value, str), "date_missing")
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise Review("date_invalid") from None
    require(moment.utcoffset() is not None, "date_timezone_missing")
    return moment


def site_date(value):
    return instant(value).astimezone(MOSCOW).strftime("%Y-%m-%d %H:%M:%S")


def end_rule(source):
    if isinstance(source, dict):
        if source.get("kind") == "datetime":
            return "At", site_date(source.get("iso"))
        if source.get("kind") == "unlimited" and not source.get("iso"):
            return "Unlimited", None
    raise Review("unknown_end_rule")


def flag(value):
    if type(value) in (bool, int, str):
        if value in (1, "1"):
            return True
        if value in (0, "0"):
            return False
    raise Review("unknown_lesson_flag")


def unpack(blob, digest=None):
    raw = zlib.decompress(blob)
    if digest is not None:
        require(sha256(raw).hexdigest() == digest, "lesson_config_hash_mismatch")
    return json.loads(raw)


@contextmanager
def complete_archive(path):
    with closing(sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        meta = dict(db.execute("SELECT key,value FROM metadata"))
        require(all(meta.get(k) == v for k, v in {
            "account": ACCOUNT, "origin": ORIGIN, "through": str(BOUND), "schema": "1",
            "capture_state": "complete"}.items()), "fresh_complete_archive_required")
        require(instant(meta.get("started_at")) <= instant(meta.get("completed_at")), "archive_dates_invalid")
        require(db.execute("PRAGMA quick_check").fetchone()[0] == "ok", "archive_integrity")
        require(not db.execute("PRAGMA foreign_key_check").fetchone(), "archive_config_missing")
        require(not db.execute("SELECT 1 FROM problems LIMIT 1").fetchone(), "unresolved_capture")
        for table in ("cards", "missing", "inventory"):
            require(not db.execute(f"SELECT 1 FROM {table} WHERE link_id NOT BETWEEN 1 AND ? LIMIT 1", (BOUND,)).fetchone(), "archive_out_of_scope")
        require(not db.execute("SELECT 1 FROM missing JOIN cards USING(link_id) LIMIT 1").fetchone(), "contradictory_inventory")
        if meta.get("scope", "range") == "inventory":
            for left, right in (("inventory", "cards"), ("cards", "inventory")):
                require(not db.execute(f"SELECT link_id FROM {left} EXCEPT SELECT link_id FROM {right} LIMIT 1").fetchone(), "incomplete_inventory")
        else:
            require(meta.get("scope", "range") == "range", "unknown_scope")
            require(db.execute("SELECT (SELECT COUNT(*) FROM cards)+(SELECT COUNT(*) FROM missing)").fetchone()[0] == BOUND, "incomplete_range")
        require(db.execute("SELECT 1 FROM cards WHERE link_id=?", (BOUND,)).fetchone(), "upper_bound_missing")
        for control_id in (EXPIRED_CONTROL, FIVE_CONTROL):
            control = db.execute("SELECT * FROM cards WHERE link_id=?", (control_id,)).fetchone()
            require(control and control["course_id"] == CONTROL_COURSE, "control_card_missing")
            newest = db.execute("SELECT MAX(link_id) FROM cards WHERE course_id=? AND contact_id=?",
                                (CONTROL_COURSE, control["contact_id"])).fetchone()[0]
            require(newest == control_id, "control_has_newer_relation")
            source = unpack(control["detail"])
            closed = source["access"]["closes_at"]
            if control_id == EXPIRED_CONTROL:
                # A still-assigned renewal lesson must not override a personal closing date.
                require(closed.get("kind") == "datetime" and instant(closed["iso"]) <= instant(control["captured_at"]),
                        "control_end_changed")
            else:
                require(closed.get("kind") == "unlimited" and source["access"]["frozen"] is False
                        and site_date(source["access"]["opens_at"]["iso"])[:16] == "2026-10-27 18:04"
                        and sorted(item["id"] for item in source["availableLessons"]) == list(FIVE_LESSONS),
                        "five_lesson_control_changed")
        yield db


def latest(db, course_id=None):
    predicate = "" if course_id is None else " WHERE course_id=?"
    bindings = () if course_id is None else (course_id,)
    # MAX is computed over *all* source rows before mapping contacts or lessons.
    query = ("SELECT c.* FROM cards c JOIN (SELECT MAX(link_id) AS id FROM cards"
             + predicate + " GROUP BY contact_id,course_id) x ON c.link_id=x.id ORDER BY c.course_id,c.link_id")
    return db.execute(query, bindings)


def config_reader(db):
    @lru_cache(maxsize=128)
    def read(digest):
        row = db.execute("SELECT payload FROM configs WHERE sha=?", (digest,)).fetchone()
        require(row is not None, "lesson_config_missing")
        rows = unpack(row[0], digest)
        require(isinstance(rows, list), "lesson_config_invalid")
        result = {item["id"]: item for item in rows}
        require(len(result) == len(rows) and all(type(k) is int and k > 0 for k in result), "invalid_lesson_identity")
        return result
    return read


def project(row, all_lessons, settings):
    """Represent personal and global bounds independently. Preserve unknowns as review.

    A personal selection is a strict allowlist. Retention of completed or visited
    lessons is disabled, including the renewal lesson after personal expiry.
    """
    detail = unpack(row["detail"])
    require(detail["course"]["id"] == row["course_id"], "course_identity_mismatch")
    access = detail["access"]
    require(type(access.get("frozen")) is bool and type(access.get("ignore_course_end")) is bool, "unknown_course_flags")
    require(access["opens_at"]["kind"] == "datetime", "personal_start_unknown")
    start = site_date(access["opens_at"]["iso"])
    personal_kind, end = end_rule(access["closes_at"])
    require(end is None or end > start, "inconsistent_personal_interval")
    course_kind, course_end = end_rule(settings["end_at"])
    observed = detail["course"].get("end_at") or {}
    if observed.get("kind") in ("unlimited", "datetime"):
        require(end_rule(observed) == (course_kind, course_end), "course_end_changed")
    course_start = settings["starts_at"]
    if course_start is not None:
        require(course_start.get("kind") == "datetime", "course_start_unknown")
        start = max(start, site_date(course_start["iso"]))
        require(end is None or end > start, "no_effective_interval")
    boundary = max(start, site_date(row["captured_at"]))
    selected = detail["availableLessons"]
    require(isinstance(selected, list), "selected_lessons_missing")
    lesson_rules = settings.get("lesson_rules", {})
    require(isinstance(lesson_rules, dict), "unknown_lesson_schedule")
    # A required report may gate the following lesson. The card alone contains
    # no proof that a particular learner submitted or passed it.
    require(all(str(rule.get("check_report")) == "0" and str(rule.get("request_report")) == "0"
                for rule in lesson_rules.values()), "report_prerequisites_need_history")
    seen, eligible = set(), []
    for item in selected:
        ident = item.get("id")
        require(type(ident) is int and ident in all_lessons and ident not in seen, "unrecognized_assigned_lesson")
        seen.add(ident)
        merged = {**all_lessons[ident], **item}
        if (ident in settings["draft_lesson_ids"] or ident in settings.get("omitted_lesson_ids", ())
                or flag(merged.get("hidden")) or not flag(merged.get("accessible"))):
            continue
        # A source flag alone cannot resolve an additional lesson timetable.
        require(merged.get("day_access") in (0, "0"), "lesson_schedule_requires_mapping")
        schedule = lesson_rules.get(str(ident))
        if schedule:
            require(str(schedule.get("day_access")) == "0", "lesson_schedule_requires_mapping")
            date = schedule.get("start_date")
            if date and date != "0000-00-00 00:00:00":
                try:
                    not_before = datetime.strptime(date, "%Y-%m-%d %H:%M:%S")
                except (ValueError, TypeError):
                    raise Review("lesson_start_unknown") from None
                require(not_before <= datetime.fromisoformat(boundary), "future_lesson_requires_schedule")
        eligible.append(ident)
    grant = {
        "status": "Frozen" if access["frozen"] else "Active",
        "frozen_at": site_date(row["captured_at"]) if access["frozen"] else None,
        "starts_at": start, "personal_end_type": personal_kind, "ends_at": end, "personal_end_days": 0,
        "course_end_type": course_kind, "course_ends_at": course_end, "ignore_course_end": int(access["ignore_course_end"]),
        "completed_retention_type": "None", "completed_retention_days": 0, "visited_retention_type": "None", "visited_retention_days": 0,
    }
    return grant, boundary, tuple(sorted(eligible))
