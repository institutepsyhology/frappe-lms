"""Bind private uploads in a student's rich-text answer to their submission."""
from urllib.parse import unquote

import frappe
from bs4 import BeautifulSoup
from frappe import _


def references(answer, allow_files):
	"""Images remain available in all text answers. File links are opt-in."""
	soup = BeautifulSoup(answer or "", "html.parser")
	images = {node.get("src") for node in soup.find_all("img", src=True)}
	files = {node.get("href") for node in soup.find_all("a", href=True)} if allow_files else set()
	return (
		{url for url in images if url.startswith("/private/files/")},
		{url for url in files if url.startswith("/private/files/")},
	)


def sync_answer_files(doc):
	previous = doc.get_doc_before_save()
	if previous and previous.answer == doc.answer:
		return
	allow_files = frappe.db.has_column("LMS Assignment", "avo_allow_attachments") and frappe.db.get_value(
		"LMS Assignment", doc.assignment, "avo_allow_attachments"
	)
	images, files = references(doc.answer, allow_files)
	before_images, before_files = references(previous.answer, allow_files) if previous else (set(), set())
	kept = images | files
	added = kept - (before_images | before_files)
	kept_paths = {unquote(url) for url in kept}
	removed = {url for url in before_images | before_files if unquote(url) not in kept_paths}
	# Frappe may keep separate File records for the same underlying bytes and URL.
	# Only bind files uploaded by this learner, and never move an existing attachment.
	for url in sorted(added | removed):
		urls = {url, unquote(url)}
		names = frappe.get_all(
			"File",
			filters={"file_url": ("in", sorted(urls)), "is_private": 1, "owner": doc.member},
			pluck="name",
			order_by="name",
		)
		files_for_url = [frappe.get_doc("File", name, for_update=True) for name in names]
		current = [f for f in files_for_url if f.owner == doc.member and f.is_private and f.file_url in urls]
		if any(f.file_url == url for f in current):
			current = [f for f in current if f.file_url == url]
		record = (doc.doctype, doc.name, "answer")
		bound = [f for f in current if (f.attached_to_doctype, f.attached_to_name, f.attached_to_field) == record]
		if url in removed:
			for f in bound:
				frappe.db.set_value(
					"File", f.name, {"attached_to_doctype": None, "attached_to_name": None, "attached_to_field": None}
				)
			continue
		if bound:
			continue
		free = next((f for f in current if not f.attached_to_doctype and not f.attached_to_name), None)
		if free and frappe.session.user == doc.member:
			frappe.db.set_value(
				"File", free.name,
				{"attached_to_doctype": doc.doctype, "attached_to_name": doc.name, "attached_to_field": "answer"},
			)
		elif url in files:
			frappe.throw(_("Attach a private file that you uploaded for this answer."))
