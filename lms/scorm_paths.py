import hashlib
import os
import re

import frappe


def chapter_package_key(chapter):
	"""Stable across title edits, including for docnames containing URL separators."""
	return "chapter-" + hashlib.sha256(chapter.encode("utf-8")).hexdigest()


def is_chapter_key(key):
	return bool(re.fullmatch(r"chapter-[0-9a-f]{64}", key))


def is_path_segment(value):
	return bool(value and value not in (".", "..") and not any(char in value for char in ("/", "\\", "\0")))


def package_dir(scorm_root, course, key):
	"""Return one direct, unaliased package directory under the site's SCORM root."""
	if not is_path_segment(course) or not is_path_segment(key):
		return None
	base = os.path.realpath(scorm_root)
	path = os.path.join(base, course, key)
	return path if os.path.realpath(path) == path else None


def stored_key(row):
	"""Older records can have a title-based directory, or just the original title."""
	if row.scorm_package_path:
		parts = [part for part in row.scorm_package_path.split("/") if part not in ("", ".")]
		if len(parts) != 3 or parts[:2] != ["scorm", row.course]:
			return None
		key = parts[2]
	else:
		key = row.title
	return key if is_path_segment(key) else None


def package_owners(course, key):
	"""Count all references, including disabled chapters, before assigning file ownership."""
	rows = frappe.get_all(
		"Course Chapter",
		filters={"course": course},
		fields=["name", "course", "title", "scorm_package_path", "is_scorm_package"],
	)
	return [
		row
		for row in rows
		if (row.scorm_package_path or row.is_scorm_package) and stored_key(row) == key
	]
