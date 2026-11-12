"""Export private identity-only MVC access JSONL without changing its source."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import uuid

from source_archive import (ACCOUNT, ORIGIN, VERIFIED_FIRST_ID, VERIFIED_LAST_ID,
                            FOREIGN_EXAMPLE_ID, SafeCode, iter_records, source_id)


def canonical(value):
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                          allow_nan=False).encode("utf-8")
    except (TypeError, ValueError):
        raise SafeCode("invalid_payload_json") from None


def _digest_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _scope_counts(archive, contacts, courses):
    counts = {"verified_scope_records": 0, "excluded_contact_records": 0,
              "excluded_course_records": 0, "excluded_overlap_records": 0,
              "expected_export_records": 0}
    db = sqlite3.connect(archive.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        rows = db.execute("""SELECT a.contact_id,a.course_id
            FROM latest p JOIN course_access a ON a.snapshot_id=p.snapshot_id
            JOIN snapshots s ON s.id=p.snapshot_id
            WHERE p.namespace=? AND p.successful=1 AND s.successful=1 AND p.link_key<>?
              AND CAST(p.link_key AS INTEGER) BETWEEN ? AND ?""",
                          (ORIGIN, FOREIGN_EXAMPLE_ID, VERIFIED_FIRST_ID, VERIFIED_LAST_ID))
        for contact, course in rows:
            excluded_contact = source_id(contact) in contacts
            excluded_course = source_id(course) in courses
            counts["verified_scope_records"] += 1
            counts["excluded_contact_records"] += excluded_contact
            counts["excluded_course_records"] += excluded_course
            counts["excluded_overlap_records"] += excluded_contact and excluded_course
            counts["expected_export_records"] += not (excluded_contact or excluded_course)
    except sqlite3.Error:
        raise SafeCode("archive_query_failed") from None
    finally:
        db.close()
    return counts


def _exclusion_metadata(values):
    ordered = sorted(values, key=int)
    return {"count": len(ordered), "sha256": hashlib.sha256(canonical(ordered)).hexdigest()}


def _publish(temporary, destination):
    """Hard-link a completed sibling file; never replace an existing path."""
    try:
        os.link(temporary, destination)
    except FileExistsError:
        raise SafeCode("destination_exists") from None
    except OSError:
        raise SafeCode("atomic_publish_failed") from None


def export_archive(archive, output_gzip, manifest_path, excluded_contact_ids=(), excluded_course_ids=()):
    """Stream canonical records into gzip and atomically publish each new file.

    No overwrite is allowed, including publication races. If publishing the
    second file fails, only this run's newly published first link is removed.
    Raw profile data, lesson titles, and target account decisions are absent.
    """
    archive, output, manifest_path = map(Path, (archive, output_gzip, manifest_path))
    if len({archive.resolve(), output.resolve(), manifest_path.resolve()}) != 3:
        raise SafeCode("destination_conflict")
    if output.exists() or manifest_path.exists():
        raise SafeCode("destination_exists")
    contacts = {source_id(value) for value in excluded_contact_ids}
    courses = {source_id(value) for value in excluded_course_ids}
    before = archive.stat()
    scope_counts = _scope_counts(archive, contacts, courses)
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    temporary = output.with_name("." + output.name + "." + token + ".tmp")
    temporary_manifest = manifest_path.with_name("." + manifest_path.name + "." + token + ".tmp")
    published = []
    try:
        record_count = lesson_count = 0
        contact_ids, course_ids, pairs = set(), set(), Counter()
        aggregate, uncompressed = hashlib.sha256(), hashlib.sha256()
        frozen, closing, lesson_flags, offsets = Counter(), Counter(), Counter(), Counter()
        earliest = latest = None
        earliest_text = latest_text = None
        with temporary.open("xb") as raw_file:
            # Empty filename and zero timestamp make gzip bytes reproducible.
            with gzip.GzipFile(filename="", fileobj=raw_file, mode="wb", mtime=0, compresslevel=6) as packed:
                for record in iter_records(archive, contacts, courses):
                    payload = canonical(record)
                    line = payload + b"\n"
                    packed.write(line)
                    uncompressed.update(line)
                    aggregate.update(record["source_access_id"].encode("ascii") + b":"
                                     + hashlib.sha256(payload).hexdigest().encode("ascii") + b"\n")
                    record_count += 1
                    lesson_count += len(record["lessons"])
                    contact_ids.add(record["source_contact_id"])
                    course_ids.add(record["source_course_id"])
                    pairs[(record["source_contact_id"], record["source_course_id"])] += 1
                    flag = record["access"]["frozen"]
                    frozen["true" if flag is True else "false" if flag is False else "unknown"] += 1
                    closing[record["access"]["closes_at"]["kind"]] += 1
                    for lesson in record["lessons"]:
                        for field in ("assigned", "accessible", "hidden"):
                            flag = lesson[field]
                            lesson_flags[field + ("_true" if flag is True else "_false" if flag is False else "_unknown")] += 1
                        offset = lesson["day_access"]
                        offsets["unknown" if offset is None else "zero" if offset == 0 else "positive" if offset > 0 else "negative"] += 1
                    captured = datetime.fromisoformat(record["captured_at"].replace("Z", "+00:00"))
                    if earliest is None or captured < earliest:
                        earliest, earliest_text = captured, record["captured_at"]
                    if latest is None or captured > latest:
                        latest, latest_text = captured, record["captured_at"]
            raw_file.flush()
            os.fsync(raw_file.fileno())
        after = archive.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise SafeCode("archive_changed_during_export")
        if record_count != scope_counts["expected_export_records"]:
            raise SafeCode("export_count_mismatch")
        duplicates = [[contact, course, count] for (contact, course), count in pairs.items() if count > 1]
        duplicates.sort(key=lambda value: (int(value[0]), int(value[1])))
        manifest = {
            "schema_version": 1, "account": ACCOUNT, "origin": ORIGIN,
            "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "source_scope": {"verified_first_access_id": VERIFIED_FIRST_ID,
                             "verified_last_access_id": VERIFIED_LAST_ID,
                             "excluded_foreign_example_id": FOREIGN_EXAMPLE_ID,
                             "historical_snapshot_date": "2026-10-13",
                             "capture_first_utc": earliest_text, "capture_last_utc": latest_text,
                             "whole_account_completeness_proven": False},
            "source_database": {"filename": archive.name, "size_bytes": before.st_size,
                                "mtime_ns": before.st_mtime_ns},
            "source_counts": scope_counts,
            "exclusions": {"contacts": _exclusion_metadata(contacts), "courses": _exclusion_metadata(courses)},
            "record_count": record_count, "lesson_count": lesson_count,
            "distinct_contact_count": len(contact_ids), "distinct_course_count": len(course_ids),
            "distinct_contact_course_pair_count": len(pairs),
            "duplicate_pair_count": len(duplicates), "additional_access_link_count": sum(value[2] - 1 for value in duplicates),
            "duplicate_contact_course_pairs": duplicates,
            "counts": {"frozen": dict(frozen), "personal_closing_kind": dict(closing),
                       "lesson_flags": dict(lesson_flags), "lesson_day_access": dict(offsets),
                       "contact_email_status": "not_available_in_relationship_archive",
                       "target_login_or_access_status": "not_inspected"},
            "payload": {"filename": output.name, "format": "canonical-jsonl-gzip", "encoding": "utf-8",
                        "compressed_size_bytes": temporary.stat().st_size,
                        "compressed_sha256": _digest_file(temporary),
                        "uncompressed_sha256": uncompressed.hexdigest(),
                        "aggregate_payload_hash": aggregate.hexdigest(),
                        "aggregate_payload_hash_method": "sha256(access_id + ':' + sha256(canonical_record_json) + newline), in file order"}}
        with temporary_manifest.open("xb") as handle:
            handle.write(canonical(manifest) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        _publish(temporary, output)
        published.append((temporary, output))
        _publish(temporary_manifest, manifest_path)
        published.append((temporary_manifest, manifest_path))
        return manifest
    except Exception:
        for temporary_file, destination in reversed(published):
            try:
                if temporary_file.samefile(destination):
                    destination.unlink()
            except FileNotFoundError:
                pass
        raise
    finally:
        temporary.unlink(missing_ok=True)
        temporary_manifest.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--exclude-course", action="append", type=int, default=[])
    args = parser.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "avo-user-import"))
    from import_mvcentr_users import load_excluded_contacts
    try:
        manifest = export_archive(args.archive, args.output, args.manifest,
                                  load_excluded_contacts(), args.exclude_course)
        print(json.dumps({"ok": True, "record_count": manifest["record_count"],
                          "lesson_count": manifest["lesson_count"],
                          "distinct_contact_count": manifest["distinct_contact_count"],
                          "distinct_course_count": manifest["distinct_course_count"],
                          "compressed_size_bytes": manifest["payload"]["compressed_size_bytes"],
                          "compressed_sha256": manifest["payload"]["compressed_sha256"]}))
        return 0
    except SafeCode as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
