"""Master Vision: dry-run by default, verified per-course plan and bounded writes.

Run inside the bench environment, after capture. Course selection only restricts
the output; it never narrows the completeness check or latest-link calculation.
"""
import argparse
from collections import Counter, defaultdict
from datetime import datetime
from itertools import islice
import json
from pathlib import Path
import shutil
import sys

from target_archive import (ACCOUNT, ORIGIN, EXPIRED_CONTROL, FIVE_CONTROL, FIVE_LESSONS, Review,
                            complete_archive, config_reader, end_rule, instant, latest, project, require)

SITE = "my-lk.mastervision.su"
PREFIX = "avo-mastervision-"


def equal(doc, values):
    for key, wanted in values.items():
        actual = doc.get(key)
        if isinstance(wanted, list):
            if len(actual or []) != len(wanted) or any(not equal(a, b) for a, b in zip(actual or [], wanted)):
                return False
        elif isinstance(actual, datetime):
            if actual.isoformat(sep=" ") != wanted:
                return False
        elif wanted in (None, "") and actual in (None, ""):
            continue
        elif actual != wanted:
            return False
    return True


def rows(fr, doctype, filters, fields):
    return fr.get_all(doctype, filters=filters, fields=fields, limit_page_length=0)


def require_site(fr):
    require(fr.local.site == SITE and fr.session.user == "Administrator", "wrong_target")
    require(fr.conf.get("individual_access_release_enabled") is True, "individual_access_disabled")
    require(fr.db.get_single_value("System Settings", "time_zone") == "Europe/Moscow", "wrong_target_timezone")
    require(all(fr.get_meta("LMS Course").has_field(f) for f in ("show_when_unavailable", "access_notice_content")),
            "course_notice_release_required")


def course(fr, course_id, *, lock):
    found = rows(fr, "LMS Course", {"custom_avo_account": ACCOUNT, "custom_avo_id": str(course_id)}, ["name"])
    require(len(found) == 1, "course_missing_or_ambiguous")
    doc = fr.get_doc("LMS Course", found[0]["name"], for_update=lock)
    require(equal(doc, {"custom_avo_account": ACCOUNT, "custom_avo_id": str(course_id), "custom_lms_id": str(course_id),
                        "disable_self_learning": 1, "published": 0}), "course_identity_or_privacy_changed")
    return doc.name


def members(fr, ids):
    """Resolve both objects by numeric source identity. Never use e-mail or names."""
    result = {}
    for offset in range(0, len(ids), 300):
        group = ids[offset:offset+300]
        filters = {"custom_avo_account": ACCOUNT, "custom_avo_contact_id": ("in", [str(i) for i in group])}
        users, contacts = defaultdict(list), defaultdict(list)
        for doctype, dest, extra in (("User", users, ["enabled"]), ("Contact", contacts, ["user"])):
            for obj in rows(fr, doctype, filters, ["name", "custom_avo_contact_id", *extra]):
                dest[obj["custom_avo_contact_id"]].append(obj)
        for ident in group:
            u, c = users[str(ident)], contacts[str(ident)]
            if len(u) == len(c) == 1 and c[0]["user"] == u[0]["name"] and u[0]["enabled"]:
                result[ident] = u[0]["name"]
    return result


def ensure_doc(fr, doctype, name, values, *, write):
    if fr.db.exists(doctype, name):
        current = fr.get_doc(doctype, name, for_update=write)
        require(equal(current, values), "existing_record_changed")
        return False
    if write:
        fr.get_doc({"doctype": doctype, **values}).insert(set_name=name)
        require(equal(fr.get_doc(doctype, name), values), "save_readback_mismatch")
    return True


def lesson_fields(name, opens):
    return {"lesson": name, "opening_type": "At", "opens_at": opens, "delay_days": 0,
            "prerequisite_state": "Satisfied", "manual_open": 0, "retain_when_limited": 0,
            "retention_end_type": "Unknown", "retention_ends_at": None}


def notice_blocks(value):
    if not value:
        return []
    try:
        data = json.loads(value)
        require(isinstance(data, dict) and isinstance(data.get("blocks"), list), "course_notice_unrecognized")
        return data["blocks"]
    except (TypeError, ValueError):
        raise Review("course_notice_unrecognized") from None


def sync_notice(fr, cname, rules, *, write):
    expected = rules["access_notice_content"]
    if expected:
        from lms.lms.utils import sanitize_editorjs
        expected = sanitize_editorjs(expected)
    blocks = notice_blocks(expected)
    show = rules["show_when_unavailable"]
    require(show in (0, 1) and not isinstance(show, str), "unknown_course_visibility")
    doc = fr.get_doc("LMS Course", cname, for_update=write)
    previous = notice_blocks(doc.get("access_notice_content"))
    if previous == blocks and doc.get("show_when_unavailable") == show:
        return
    require(not previous or previous == blocks, "existing_course_notice_differs")
    require(not fr.db.exists("LMS Access Policy", {"course": cname}), "managed_course_visibility_changed")
    if write:
        from lms.lms.access_presentation import save_visibility_settings
        save_visibility_settings(course=cname, show_when_unavailable=show, access_notice_content=expected)
        saved = fr.get_doc("LMS Course", cname)
        require(saved.get("show_when_unavailable") == show and
                notice_blocks(saved.get("access_notice_content")) == blocks, "course_notice_readback_mismatch")


def verify_learner_access(fr, cname, member, grant, assigned, others, opening, *, control):
    from lms.lms.access_presentation import course_state, lesson_notice
    from lms.lms.permissions import can_access_lesson, can_author_course
    from lms.lms.individual_access import grant_allows_lesson

    selected = tuple(assigned)
    inclusion = next(iter(selected), None)
    exclusion = next(iter(others), None)
    now = fr.utils.now_datetime().isoformat(sep=" ", timespec="seconds")
    allowed_now = (grant["status"] == "Active" and now >= max(grant["starts_at"], opening) and
                   (not grant["ends_at"] or now < grant["ends_at"]) and
                   (grant["ignore_course_end"] or not grant["course_ends_at"] or now < grant["course_ends_at"]))
    if inclusion:
        require(bool(grant_allows_lesson(user=member, lesson=inclusion)) == allowed_now, "effective_assignment_mismatch")
    if exclusion:
        require(not grant_allows_lesson(user=member, lesson=exclusion), "unassigned_lesson_accessible")
    if not can_author_course(cname, user=member):
        if inclusion:
            require(bool(can_access_lesson(inclusion, user=member)) == allowed_now, "learner_route_mismatch")
        if exclusion:
            require(not can_access_lesson(exclusion, user=member), "learner_can_open_unassigned_lesson")
    if control == EXPIRED_CONTROL:
        require(course_state(cname, member)["status"] == "Expired" and inclusion, "control_course_not_expired")
        notice = lesson_notice(cname, inclusion, member)
        require(notice.get("access_denied") and notice.get("notice_content"), "control_closed_notice_missing")
    elif control == FIVE_CONTROL:
        require(len(selected) == 5 and exclusion and course_state(cname, member)["status"] == "Active",
                "five_lesson_control_not_active")
        require(all(grant_allows_lesson(user=member, lesson=name) and can_access_lesson(name, user=member)
                    for name in selected), "five_assigned_lessons_not_open")
        require(not can_access_lesson(exclusion, user=member), "five_lesson_control_opens_neighbor")


def course_plan(fr, db, cid, rules, read_config, *, write, omitted, batch=None, verify=None):
    """Called inside a Frappe transaction; a course lock serializes overlapping imports."""
    cname = course(fr, cid, lock=write)
    require(rules.get("course_id") == cid, "course_rules_identity")
    require(rules.get("permanent_lesson_access") is False, "completed_lesson_history_required")
    rules = {**rules, "omitted_lesson_ids": omitted}
    global_type, global_end = end_rule(rules["end_at"])
    policy = {"course": cname, "enabled": 1, "global_end_type": global_type, "global_end_at": global_end,
              "default_personal_end_type": "Unknown", "default_personal_end_days": 0, "default_personal_end_at": None,
              "completed_retention_type": "None", "completed_retention_days": 0,
              "visited_retention_type": "None", "visited_retention_days": 0,
              "lessons": []}
    policy_name = f"{PREFIX}policy-{cid}"
    policies = rows(fr, "LMS Access Policy", {"course": cname}, ["name"])
    require(all(r["name"] == policy_name for r in policies), "existing_unmanaged_policy")

    # Resolve only the authoritative links in this course, including expired ones.
    winners = db.execute("SELECT contact_id, MAX(link_id) AS link_id FROM cards WHERE course_id=? GROUP BY contact_id",
                         (cid,)) if batch is None else batch
    winner_ids = {r["contact_id"]: r["link_id"] for r in winners}
    mapped = members(fr, list(winner_ids))
    counts = Counter({"pending_contact": len(winner_ids) - len(mapped), "pairs": len(winner_ids)})
    def ename(i):
        return f"{PREFIX}enrollment-{i}-{cid}"
    def gname(i):
        return f"{PREFIX}grant-{winner_ids[i]}"
    for dt, naming in (("LMS Access Grant", gname), ("LMS Enrollment", ename)):
        expected = {naming(i): member for i, member in mapped.items()}
        filters = {"course": cname}
        if batch is not None:
            # Before creating a policy the locked course must be free of external
            # access. Once it exists we only alter the current, rechecked pairs.
            if not policies:
                require(not fr.db.exists(dt, {"course": cname}), "course_access_changed_since_preflight")
            if not mapped:
                continue
            filters["member"] = ("in", list(mapped.values()))
        existing = rows(fr, dt, filters, ["name", "member"])
        require(all(expected.get(r["name"]) == r["member"] for r in existing), "unmanaged_or_previous_access_exists")
    if not mapped:
        return counts

    lessons = {}
    for item in rows(fr, "Course Lesson", {"course": cname}, ["name", "course", "custom_avo_account",
                "custom_avo_id", "custom_lms_id", "include_in_preview", "is_draft", "publication_audience"]):
        if item.get("custom_avo_account") != ACCOUNT:
            continue
        lid = item["custom_avo_id"]
        require(isinstance(lid, str) and lid.isascii() and lid.isdecimal() and str(int(lid)) == lid
                and item["custom_lms_id"] == lid and int(lid) not in lessons, "lesson_identity_mismatch")
        lessons[int(lid)] = item
    policy_initialized = False
    released = set()
    for source in (latest(db, cid) if batch is None else batch):
        ident = source["contact_id"]
        if ident not in mapped:
            continue
        # A missing schedule or unmigrated lesson concerns this pair. Other
        # members in a large club need not wait for it. Never leave a changed
        # previously-managed grant unreported by treating it as a new omission.
        config = read_config(source["config_sha"])
        try:
            grant, opening, allowed = project(source, config, rules)
            require(source["link_id"] != FIVE_CONTROL or allowed == FIVE_LESSONS, "five_lesson_control_selection_mismatch")
            require(all(lid in lessons for lid in allowed), "assigned_lesson_missing_from_course")
        except Review as issue:
            require(not fr.db.exists("LMS Access Grant", gname(ident))
                    and not fr.db.exists("LMS Enrollment", ename(ident)), "previously_applied_pair_needs_review")
            counts["pending_relation"] += 1
            counts["deferred_" + str(issue)] += 1
            continue
        provenance = {"course": cname, "member": mapped[ident], "access_source": "Import",
                      "source_reference": f"mastervision:contacttraining:{source['link_id']}"}
        if not policy_initialized:
            sync_notice(fr, cname, rules, write=write)
            ensure_doc(fr, "LMS Access Policy", policy_name, policy, write=write)
            policy_initialized = True
        counts["new_grants"] += ensure_doc(fr, "LMS Access Grant", gname(ident),
            {**provenance, **grant, "lessons": [lesson_fields(lessons[lid]["name"], opening) for lid in allowed]}, write=write)
        counts["new_enrollments"] += ensure_doc(fr, "LMS Enrollment", ename(ident),
            {**provenance, "member_type": "Student", "role": "Member"}, write=write)
        counts["grant_lesson_rows"] += len(allowed)
        for lid in allowed:
            if lid in released:
                continue
            item = lessons[lid]
            require(item["include_in_preview"] == 0 and item.get("publication_audience") in (None, "", "All"),
                    "unmanaged_lesson_publication")
            if item["is_draft"]:
                counts["lessons_for_assigned_students"] += 1
                if write:
                    # The normal 'publish to All' action would append a row to OTHER grants.
                    doc = fr.get_doc("Course Lesson", item["name"], for_update=True)
                    require(equal(doc, item), "lesson_changed_during_import")
                    doc.flags.lesson_publication_action = True
                    flags = {"is_draft": 0, "publication_audience": "All", "include_in_preview": 0}
                    doc.update(flags)
                    doc.lesson_published_at = doc.lesson_published_at or fr.utils.now_datetime()
                    doc.save()
                    require(equal(fr.get_doc("Course Lesson", item["name"]), {**item, **flags}), "lesson_release_readback")
            released.add(lid)
        control = source["link_id"] if source["link_id"] in (EXPIRED_CONTROL, FIVE_CONTROL) else None
        if verify and write and (counts["mapped"] == 0 or control):
            rights = frozenset(allowed)
            other_ids = (lid for lid in lessons if lid not in rights and lid not in rules["draft_lesson_ids"])
            if control == FIVE_CONTROL:
                other_ids = sorted(other_ids, key=lambda lid: (abs(lid - FIVE_LESSONS[-1]), lid))
            verify(fr, cname, mapped[ident], grant, (lessons[lid]["name"] for lid in allowed),
                   (lessons[lid]["name"] for lid in other_ids), opening, control=control)
        counts["mapped"] += 1
    return counts


def run(fr, source_path, manifest, *, write=False, course_id=None, exclusions, fresh_rules, on_progress=None):
    require_site(fr)
    require(manifest["account"] == ACCOUNT and manifest["origin"] == ORIGIN, "wrong_course_rules")
    with complete_archive(source_path) as db:
        read_config = config_reader(db)
        ids = [row[0] for row in db.execute("SELECT DISTINCT course_id FROM cards ORDER BY course_id")]
        if course_id is not None:
            require(course_id in ids, "course_not_in_archive")
            ids = [course_id]
        capture_start = instant(db.execute("SELECT value FROM metadata WHERE key='started_at'").fetchone()[0])
        for cid in ids:
            committed = 0
            fr.db.begin()
            try:
                archived = manifest["courses"].get(str(cid))
                require(archived is not None, "course_rules_missing")
                try:
                    rules = fresh_rules(cid, archived, capture_start)
                except (ValueError, KeyError, TypeError) as error:
                    if isinstance(error, Review):
                        raise
                    raise Review("fresh_course_settings_unrecognized") from None
                omitted = exclusions(cid)
                counts = course_plan(fr, db, cid, rules, read_config, write=False, omitted=omitted)
                fr.db.rollback()
                if write and counts["mapped"]:
                    counts = Counter()
                    winners = latest(db, cid)
                    while batch := list(islice(winners, 100)):
                        if shutil.disk_usage(Path(source_path).parent).free < 384 * 1024 * 1024:
                            raise OSError("insufficient_space_for_batch")
                        fr.db.begin()
                        current = course_plan(fr, db, cid, rules, read_config, write=True, omitted=omitted, batch=batch,
                                              verify=verify_learner_access)
                        fr.db.commit()
                        committed += current["mapped"]
                        counts.update(current)
                        if on_progress:
                            on_progress({"course_id": cid, "status": "batch_verified", "mapped": committed})
            except Review as error:
                fr.db.rollback()
                yield {"course_id": cid, "status": "review", "reason": str(error), "already_committed": committed}
                continue
            except BaseException:
                fr.db.rollback()
                raise
            yield {"course_id": cid, "status": "applied" if write else "preview", **counts}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--archive", required=True)
    p.add_argument("--rules", required=True)
    p.add_argument("--sites", default="/home/frappe/frappe-bench/sites")
    p.add_argument("--course", type=int)
    p.add_argument("--apply", action="store_true")
    args = p.parse_args()
    from frappe import init, connect, destroy, set_user
    import frappe
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "mastervision-migration"))
    from lesson_policy import excluded_ids, deferred_ids
    from course_rules import read_fresh_rules
    manifest = json.loads(Path(args.rules).read_text(encoding="utf-8"))
    archive_path = Path(args.archive).resolve()
    policy_root = archive_path.parent / "policies"
    def fresh_rules(cid, archived, capture_start):
        path = policy_root / f"{cid}.json"
        require(path.is_file(), "fresh_course_settings_missing")
        settings = json.loads(path.read_text(encoding="utf-8-sig"))
        require(settings.get("course_id") == cid and settings.get("source_origin") == ORIGIN,
                "fresh_course_settings_identity")
        require(instant(settings.get("captured_at")) >= capture_start, "stale_course_settings")
        return read_fresh_rules(settings, archived)
    init(site=SITE, sites_path=args.sites)
    try:
        connect()
        set_user("Administrator")
        incomplete = False
        log = lambda row: print(json.dumps(row, ensure_ascii=True), flush=True)
        for report in run(frappe, archive_path, manifest, write=args.apply, course_id=args.course,
                          exclusions=lambda cid: excluded_ids(cid) | deferred_ids(cid), fresh_rules=fresh_rules, on_progress=log):
            print(json.dumps(report, ensure_ascii=True), flush=True)
            incomplete |= bool(report["status"] == "review" or report.get("pending_contact") or report.get("pending_relation"))
        return 2 if incomplete else 0
    finally:
        destroy()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        # Never leak personal document names or database details into process logs.
        reason = str(exc) if isinstance(exc, Review) else type(exc).__name__
        print(json.dumps({"status": "stopped", "reason": reason}), flush=True)
        sys.exit(1)
