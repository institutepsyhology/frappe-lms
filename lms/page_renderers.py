"""Serve course packages after checking the learner's access to the owning chapter."""

import mimetypes
import os
from urllib.parse import unquote

import frappe
from frappe.website.page_renderers.base_renderer import BaseRenderer
from werkzeug.wrappers import Response
from werkzeug.wsgi import wrap_file

from lms.scorm_paths import chapter_package_key, is_chapter_key, is_path_segment, package_dir, package_owners


class SCORMRenderer(BaseRenderer):
	def can_render(self):
		return self.path.lstrip("/").startswith("scorm/")

	def _parts(self):
		parts = [unquote(part) for part in self.path.strip("/").split("/")]
		if len(parts) < 3 or parts[0] != "scorm" or not all(is_path_segment(part) for part in parts):
			raise frappe.PermissionError
		return parts

	def _check_permission(self):
		from lms.lms.doctype.course_chapter.course_chapter import get_scorm_lesson, resolve_scorm_access

		_, course, key, *_ = self._parts()
		owners = package_owners(course, key)
		if len(owners) != 1 or not owners[0].is_scorm_package:
			raise frappe.PermissionError
		chapter = owners[0].name
		if is_chapter_key(key) and key != chapter_package_key(chapter):
			raise frappe.PermissionError
		access = resolve_scorm_access(course, get_scorm_lesson(chapter))
		if not access.can_access or access.locked:
			raise frappe.PermissionError

	def _is_safe_path(self, path):
		_, course, key, *_ = self._parts()
		resolved = os.path.realpath(path)
		for base in ("private", "public"):
			root = package_dir(frappe.get_site_path(base, "scorm"), course, key)
			if root and (resolved == root or resolved.startswith(root + os.sep)):
				return True
		return False

	def _serve_file(self, path):
		f = open(path, "rb")
		response = Response(wrap_file(frappe.local.request.environ, f), direct_passthrough=True)
		response.mimetype = mimetypes.guess_type(path)[0]
		response.headers["Cache-Control"] = "private, no-store"
		return response

	def render(self):
		self._check_permission()
		_, course, key, *resource = self._parts()
		roots = ("private",) if is_chapter_key(key) else ("private", "public")
		for base in roots:
			directory = package_dir(frappe.get_site_path(base, "scorm"), course, key)
			if directory and os.path.isdir(directory):
				return self._render_from_root(directory, resource)
		return None

	def _render_from_root(self, directory, resource):
		path = os.path.join(directory, *resource)
		candidates = [path]
		if resource and not os.path.splitext(path)[1]:
			candidates.append(path + ".html")
		candidates.append(os.path.join(path, "index.html"))
		for candidate in candidates:
			if os.path.isfile(candidate):
				return self._serve_package_file(directory, candidate)
		if resource:
			# Some legacy players request a nested asset using only its filename.
			for folder, _, files in os.walk(directory):
				if resource[-1] in files:
					return self._serve_package_file(directory, os.path.join(folder, resource[-1]))
		return None

	def _serve_package_file(self, directory, path):
		resolved = os.path.realpath(path)
		if not resolved.startswith(directory + os.sep):
			raise frappe.PermissionError
		return self._serve_file(resolved)
