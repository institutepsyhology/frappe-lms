"""Read Master Vision CSV exports into an ID-only, source-bound selection.

No files are written. Other contact fields are discarded as each CSV record is
read. The returned manifest contains hashes/counts and source basenames, never
cell values or absolute paths. CP1251 requires an explicit encoding argument;
unmarked input otherwise must be valid UTF-8. UTF-16 requires its BOM.
"""
import codecs
import csv
import hashlib
import io
import itertools
import json
import os
from pathlib import Path
import stat


ACCOUNT = "mastervision"
FORMAT = "mastervision-contact-selection-v1"
EXPECTED_COLUMNS = 41
MAX_FIELD_CHARS = 1024 * 1024


class SelectionError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class _HashingReader(io.RawIOBase):
    def __init__(self, source):
        super().__init__()
        self.source = source
        self.digest = hashlib.sha256()
        self.bytes_read = 0

    def readable(self):
        return True

    def readinto(self, buffer):
        count = self.source.readinto(buffer)
        if count:
            self.digest.update(memoryview(buffer)[:count])
            self.bytes_read += count
        return count


def _signature(info):
    # Windows stat/fstat can expose different creation/change-time semantics.
    # File identity, size and modification time are comparable on both paths.
    change_time = info.st_ctime_ns if os.name != "nt" else None
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, change_time)


def _codec(prefix, requested):
    if requested not in (None, "utf-8", "utf-8-sig", "utf-16", "utf-16-le", "utf-16-be", "cp1251"):
        raise SelectionError("encoding_unsupported")
    if prefix.startswith((codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE)):
        raise SelectionError("encoding_unsupported")
    if prefix.startswith(codecs.BOM_UTF8):
        if requested not in (None, "utf-8", "utf-8-sig"):
            raise SelectionError("encoding_conflict")
        return "utf-8-sig", "utf-8-bom"
    for bom, endian in ((codecs.BOM_UTF16_LE, "utf-16-le"), (codecs.BOM_UTF16_BE, "utf-16-be")):
        if prefix.startswith(bom):
            if requested not in (None, "utf-16", endian):
                raise SelectionError("encoding_conflict")
            return "utf-16", endian + "-bom"
    if requested == "cp1251":
        return "cp1251", "cp1251-explicit"
    if requested not in (None, "utf-8", "utf-8-sig"):
        raise SelectionError("encoding_conflict")
    return "utf-8", "utf-8"


def _source_id(value):
    if value == "":
        raise SelectionError("id_blank")
    if not (
        0 < len(value) <= 19
        and value.isascii()
        and value.isdecimal()
        and value[0] != "0"
        and int(value) < 2**63
    ):
        raise SelectionError("id_invalid")
    return int(value)


def _read_file(path, encoding):
    try:
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode):
            raise SelectionError("source_not_regular")
        with path.open("rb") as source:
            if _signature(before) != _signature(os.fstat(source.fileno())):
                raise SelectionError("source_changed")
            prefix = source.read(4)
            source.seek(0)
            decoder, encoding_label = _codec(prefix, encoding)
            hashed = _HashingReader(source)
            ids = set()
            rows = 0
            with io.TextIOWrapper(io.BufferedReader(hashed), encoding=decoder, errors="strict", newline="") as text:
                reader = csv.reader(text, delimiter=";", strict=True)
                header = next(reader, None)
                if not header or len(header) != EXPECTED_COLUMNS or header[0] != "ID":
                    raise SelectionError("header_invalid")
                header_hash = hashlib.sha256(
                    json.dumps(header, ensure_ascii=True, separators=(",", ":")).encode("ascii")
                ).hexdigest()
                for row in reader:
                    if not row:
                        raise SelectionError("id_blank")
                    if len(row) != EXPECTED_COLUMNS:
                        raise SelectionError("row_width")
                    ids.add(_source_id(row[0]))
                    rows += 1
            after = os.fstat(source.fileno())
        if (
            _signature(before) != _signature(after)
            or _signature(before) != _signature(path.lstat())
            or hashed.bytes_read != before.st_size
        ):
            raise SelectionError("source_changed")
    except UnicodeError:
        raise SelectionError("encoding_invalid") from None
    except csv.Error:
        raise SelectionError("csv_invalid") from None
    except OSError:
        raise SelectionError("source_unreadable") from None
    return ids, {
        "name": path.name,
        "bytes": before.st_size,
        "sha256": hashed.digest.hexdigest(),
        "encoding": encoding_label,
        "header": {"columns": EXPECTED_COLUMNS, "id_column": "ID", "sha256": header_hash},
        "rows": rows,
        "unique_count": len(ids),
        "duplicate_rows": rows - len(ids),
    }, _signature(before)


def build_selection(paths, *, encoding=None):
    """Return ``{'ids': sorted_ints, 'manifest': safe_provenance}``.

    Every source must have the same 41-column header beginning with exact ASCII
    ``ID``. Any invalid ID, decoding error, malformed record or source mutation
    invalidates the entire selection with a fixed ``SelectionError.code``.
    """
    if isinstance(paths, (str, bytes, os.PathLike)):
        raise SelectionError("paths_invalid")
    try:
        paths = tuple(Path(path) for path in paths)
    except (TypeError, ValueError):
        raise SelectionError("paths_invalid") from None
    if not paths:
        raise SelectionError("paths_invalid")

    per_file = []
    reports = []
    source_signatures = []
    old_field_limit = csv.field_size_limit()
    try:
        csv.field_size_limit(MAX_FIELD_CHARS)
        for path in paths:
            ids, report, signature = _read_file(path, encoding)
            if reports and report["header"] != reports[0]["header"]:
                raise SelectionError("header_mismatch")
            per_file.append(ids)
            reports.append(report)
            source_signatures.append(signature)
    finally:
        csv.field_size_limit(old_field_limit)

    union = set().union(*per_file)
    if not union:
        raise SelectionError("selection_empty")
    ids = sorted(union)
    fingerprint = hashlib.sha256()
    for source_id in ids:
        fingerprint.update(f"{source_id}\n".encode("ascii"))
    pairs = [
        {"files": [i, j], "count": len(per_file[i] & per_file[j])}
        for i, j in itertools.combinations(range(len(per_file)), 2)
    ]
    # Count distinct overlapping identities separately from extra memberships:
    # an ID appearing in three exports contributes one identity, two extras.
    seen = set()
    repeated_ids = set()
    for members in per_file:
        repeated_ids.update(seen & members)
        seen.update(members)
    rows = sum(report["rows"] for report in reports)
    try:
        if any(_signature(path.lstat()) != expected for path, expected in zip(paths, source_signatures)):
            raise SelectionError("source_changed")
    except OSError:
        raise SelectionError("source_changed") from None
    return {"ids": ids, "manifest": {
        "format": FORMAT,
        "account": ACCOUNT,
        "files": reports,
        "rows": rows,
        "union_count": len(ids),
        "fingerprint": fingerprint.hexdigest(),
        "intrafile_duplicate_rows": sum(report["duplicate_rows"] for report in reports),
        "interfile_repeated_memberships": sum(map(len, per_file)) - len(ids),
        "interfile_duplicate_ids": len(repeated_ids),
        "total_duplicate_rows": rows - len(ids),
        "pair_overlaps": pairs,
        "all_files_overlap": len(set.intersection(*per_file)) if len(per_file) > 1 else 0,
    }}
