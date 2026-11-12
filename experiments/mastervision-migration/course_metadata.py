"""Create only source-confirmed empty MasterVision draft course parents."""
from importer import ACCOUNT, ORIGIN, SITE, Review, Stop, source_id
import source


FIELDS = ["name", "custom_avo_account", "custom_avo_id", "custom_lms_id", "published", "disable_self_learning"]
CREATE_FIELDS = {"title", "short_introduction", "description", "published", "disable_self_learning",
                 "custom_avo_account", "custom_avo_id", "custom_lms_id", "instructors"}


def _binding(client):
    if (ACCOUNT, ORIGIN, SITE) != ("mastervision", "https://shop.mastervision.su", "my-lk.mastervision.su") or (
            getattr(client, "account", None), getattr(client, "site", None)) != (ACCOUNT, SITE):
        raise Stop("wrong_frappe_site")


def _source(record):
    if not isinstance(record, dict) or (record.get("account"), record.get("origin")) != (ACCOUNT, ORIGIN):
        raise Stop("empty_course_source_account_mismatch")
    if record.get("verified") is not True or record.get("error") not in (None, ""):
        raise Review("empty_course_source_unverified")
    parsed, html = record.get("parsed"), record.get("html")
    if not isinstance(parsed, dict) or not isinstance(html, str) or not html:
        raise Review("empty_course_source_invalid")
    cid = parsed.get("course_id")
    if type(cid) is not int:
        raise Review("empty_course_source_invalid")
    canonical = source_id(cid)
    title = parsed.get("title")
    if not isinstance(title, str) or not title.strip() or len(title) > 512:
        raise Review("empty_course_title_invalid")
    keys = ("course_id", "title", "lesson_ids", "lessons", "tree", "empty_reason")
    if any(parsed.get(key) != [] for key in ("lesson_ids", "lessons", "tree")) or parsed.get("empty_reason") != "empty_course_tree":
        raise Review("source_course_not_empty")
    try:
        reparsed = source.parse_course(html, cid)
    except source.Review as error:
        if str(error) == "source_auth_error":
            raise Stop("source_auth_error") from None
        raise Review("empty_course_source_invalid") from None
    if any(reparsed.get(key) != parsed.get(key) for key in keys):
        raise Review("empty_course_source_invalid")
    return canonical, title


def _read(client, tool, arguments):
    _binding(client)
    try:
        result = client.call(tool, arguments)
    except (Review, Stop):
        raise
    except Exception:
        raise Stop("empty_course_read_failed") from None
    if not isinstance(result, dict):
        raise Stop("empty_course_read_invalid")
    return result


def _rows(client, doctype, filters, fields=None, limit=2):
    result = _read(client, "list_documents", {"doctype": doctype, "fields": fields or ["name"],
                                            "filters": filters, "limit": limit})
    rows = result.get("documents")
    if not isinstance(rows, list) or result.get("has_next_page") is not False or any(not isinstance(row, dict) for row in rows):
        raise Review("empty_course_target_ambiguous")
    return rows


def _identity(doc, cid):
    if (not isinstance(doc, dict) or not isinstance(doc.get("name"), str) or not doc["name"]
            or doc.get("custom_avo_account") != ACCOUNT or doc.get("custom_avo_id") != cid
            or doc.get("custom_lms_id") != cid or type(doc.get("published")) is not int or doc["published"] != 0
            or type(doc.get("disable_self_learning")) is not int or doc["disable_self_learning"] != 1):
        raise Review("empty_course_target_identity_invalid")


def _document(doc, cid, title):
    _identity(doc, cid)
    if (any(doc.get(key) != title for key in ("title", "short_introduction", "description"))
            or doc.get("chapters") != []):
        raise Review("empty_course_metadata_conflict")


def _lookup(client, cid, title):
    matches = _rows(client, "LMS Course", [["custom_avo_account", "=", ACCOUNT], ["custom_avo_id", "=", cid]], FIELDS)
    numbers = _rows(client, "LMS Course", [["custom_lms_id", "=", cid]], FIELDS)
    if len(matches) > 1 or len(numbers) > 1:
        raise Review("empty_course_target_ambiguous")
    if not matches:
        if numbers:
            raise Review("empty_course_number_conflict")
        return None
    row = matches[0]
    _identity(row, cid)
    if len(numbers) != 1 or numbers[0].get("name") != row["name"]:
        raise Review("empty_course_number_conflict")
    _identity(numbers[0], cid)
    doc = _read(client, "get_document", {"doctype": "LMS Course", "name": row["name"]})
    _document(doc, cid, title)
    if doc["name"] != row["name"]:
        raise Review("empty_course_target_identity_invalid")
    # No chapter/lesson or learner-rights row is created, changed or deleted here.
    for doctype in ("Course Chapter", "Course Lesson", "LMS Enrollment", "LMS Access Grant"):
        if _rows(client, doctype, [["course", "=", doc["name"]]], limit=1):
            raise Review("empty_course_not_empty")
    return doc


def _create(client, data):
    """One narrowly guarded capability; the generic client's allowlist stays closed."""
    _binding(client)
    if (not isinstance(data, dict) or set(data) != CREATE_FIELDS or data.get("published") != 0
            or data.get("disable_self_learning") != 1 or data.get("custom_avo_account") != ACCOUNT
            or not isinstance(data.get("custom_avo_id"), str) or data.get("custom_lms_id") != data["custom_avo_id"]
            or data.get("instructors") != [{"instructor": "Administrator"}]
            or not isinstance(data.get("title"), str) or not data["title"].strip() or len(data["title"]) > 512
            or any(data.get(key) != data["title"] for key in ("short_introduction", "description"))):
        raise Stop("empty_course_mutation_not_allowed")
    try:
        if source_id(data["custom_avo_id"]) != data["custom_avo_id"]:
            raise Review("invalid_source_identity")
    except Review:
        raise Stop("empty_course_mutation_not_allowed") from None
    try:
        response = client.rpc("tools/call", {"name": "create_document", "arguments": {"doctype": "LMS Course", "data": data}})
    except BaseException:
        raise Stop("empty_course_write_uncertain") from None
    if not isinstance(response, dict) or response.get("isError") or not isinstance(response.get("structuredContent"), dict):
        raise Stop("empty_course_write_uncertain")
    return response["structuredContent"]


def ensure_empty_course(client, source_snapshot, apply=False):
    """Check a verified empty source, optionally create one private draft parent.

    No lesson, access, publication, numbering configuration or existing metadata
    is changed. An uncertain creation must stop the caller's whole import run.
    """
    _binding(client)
    if type(apply) is not bool:
        raise Review("empty_course_input_invalid")
    cid, title = _source(source_snapshot)
    existing = _lookup(client, cid, title)
    result = {"account": ACCOUNT, "course_id": cid, "lesson_ids": [], "empty": True}
    if existing is not None:
        return {**result, "status": "already_present"}
    if not apply:
        return {**result, "status": "ready"}
    if _lookup(client, cid, title) is not None:
        raise Stop("empty_course_target_changed")
    data = {"title": title, "short_introduction": title, "description": title, "published": 0,
            "disable_self_learning": 1, "custom_avo_account": ACCOUNT, "custom_avo_id": cid, "custom_lms_id": cid,
            "instructors": [{"instructor": "Administrator"}]}
    created = _create(client, data)
    try:
        _document(created, cid, title)
        final = _lookup(client, cid, title)
        if final is None or final["name"] != created["name"]:
            raise Stop("empty_course_write_uncertain")
    except BaseException:
        raise Stop("empty_course_write_uncertain") from None
    return {**result, "status": "created"}
