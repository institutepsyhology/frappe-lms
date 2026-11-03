"""Run synthetic import checks only on the named, isolated Frappe test site."""
import base64
import io
import json
import secrets

import frappe
from PIL import Image
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

SITE = "access-stage2.local"


def main():
    frappe.init(site=SITE)
    frappe.connect()
    try:
        if str(frappe.local.site) != SITE:
            raise RuntimeError("unexpected_test_site")
        frappe.set_user("Administrator")
        from lms.lms import avo_import

        # These mapping fields are scoped to the isolated stage site.
        fields = {}
        for doctype in ("LMS Course", "Course Lesson"):
            fields[doctype] = [
                {"fieldname": "custom_avo_id", "label": "AVO ID", "fieldtype": "Data", "insert_after": "title"},
                {"fieldname": "custom_avo_account", "label": "AVO Account", "fieldtype": "Data", "insert_after": "custom_avo_id"},
            ]
        create_custom_fields(fields, update=False)
        frappe.db.commit()
        avo_import.SITE_ACCOUNTS[SITE] = ("mv-centr", "https://shop.mv-centr.ru")
        identifier = str(90000000000000 + secrets.randbelow(9999999999999))
        image = io.BytesIO()
        Image.new("RGB", (2, 2), "red").save(image, format="PNG")
        raw_image = image.getvalue()
        images = {"one": base64.b64encode(raw_image).decode("ascii")}
        payload = {"account": "mv-centr", "source_origin": "https://shop.mv-centr.ru",
                   "course_id": identifier, "lesson_id": identifier, "format": "preview",
                   "course_title": "AVO MCP synthetic isolated test", "lesson_title": "Synthetic test lesson",
                   "content": [
                       {"type": "text", "text": "Hello, {name}!"},
                       {"type": "image", "image_key": "one", "caption": "Test screenshot"},
                       {"type": "video_pair", "players": [
                           {"provider": "youtube", "url": "https://youtu.be/abcdefghijk"},
                           {"provider": "rutube", "url": "https://rutube.ru/video/0123456789abcdef0123456789abcdef/"}]}]}
        before = {d: frappe.db.count(d) for d in ("LMS Course", "Course Lesson", "LMS Enrollment")}
        preview = avo_import.import_lesson(payload, images)
        if not preview["ready"] or not preview["dry_run"] or preview["action"] != "create_course_and_lesson":
            raise RuntimeError("dry_run_failed")
        if before != {d: frappe.db.count(d) for d in before}:
            raise RuntimeError("dry_run_changed_data")
        result = avo_import.import_lesson(payload, images, dry_run=False)
        if result["action"] != "created" or result["source_complete"]:
            raise RuntimeError("create_failed")
        frappe.db.commit()  # also releases the import lock
        course = frappe.get_doc("LMS Course", result["course"])
        lesson = frappe.get_doc("Course Lesson", result["lesson"])
        if course.published or not lesson.is_draft or lesson.course != course.name:
            raise RuntimeError("draft_or_course_mismatch")
        if course.custom_avo_id != identifier or lesson.custom_avo_id != identifier:
            raise RuntimeError("source_id_mismatch")
        content = json.loads(lesson.content)
        if [b["type"] for b in content["blocks"]] != ["paragraph", "image", "videoChoice"]:
            raise RuntimeError("block_mismatch")
        if "{name}" not in content["blocks"][0]["data"]["text"]:
            raise RuntimeError("template_lost")
        image_url = content["blocks"][1]["data"]["url"]
        if not image_url.startswith("/private/files/"):
            raise RuntimeError("image_not_private")
        pairs = content["blocks"][2]["data"]
        if pairs["youtube"] != "https://youtu.be/abcdefghijk" or pairs["rutube"] != "https://rutube.ru/video/0123456789abcdef0123456789abcdef/":
            raise RuntimeError("video_mismatch")
        rows = frappe.get_all("File", filters={"attached_to_doctype": "Course Lesson",
            "attached_to_name": lesson.name}, fields=["file_name", "is_private"])
        if len(rows) != 2 or any(not row.is_private for row in rows):
            raise RuntimeError("private_attachments_missing")
        replay = avo_import.import_lesson(payload, images, dry_run=False)
        if replay["action"] != "already_imported" or replay["lesson"] != lesson.name:
            raise RuntimeError("replay_failed")
        frappe.db.commit()
        changed = dict(payload, lesson_title="Changed synthetic test")
        try:
            avo_import.import_lesson(changed, images, dry_run=False)
        except ValueError:
            frappe.db.rollback()
        else:
            raise RuntimeError("changed_replay_accepted")
        if frappe.db.count("LMS Enrollment") != before["LMS Enrollment"]:
            raise RuntimeError("unexpected_enrollment")
        print("AVO_STAGE_RESULT:" + json.dumps({"ok": True, "dry_run": True,
            "private_images_and_snapshot": True, "replay": True, "conflict_rejected": True,
            "draft": True, "source_id": True, "no_enrollment": True}))
    finally:
        frappe.destroy()


if __name__ == "__main__":
    main()
