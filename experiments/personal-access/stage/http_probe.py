"""Exercise access over HTTP on the isolated test site only; creates synthetic data."""

import http.cookiejar
import json
import secrets
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import frappe
from frappe.utils import add_to_date, now_datetime
from frappe.utils.file_manager import save_file

from lms.lms.test_helpers import BaseTestUtils

SITE = "access-stage2.local"
ROOT = "/home/frappe/frappe-bench"
BASE = "http://127.0.0.1:8000"


def bench_config(value):
	result = subprocess.run(["bench", "--site", SITE, "set-config", "individual_access_release_enabled",
		"True" if value else "False", "--parse"], cwd=ROOT, capture_output=True, timeout=60)
	if result.returncode:
		raise RuntimeError("test site configuration failed")


def call(opener, path, data=None):
	request = urllib.request.Request(BASE + path, data=data, headers={"Host": SITE})
	try:
		with opener.open(request, timeout=15) as response:
			return response.status, response.read()
	except urllib.error.HTTPError as error:
		return error.code, error.read()


def main():
	if frappe.local.site != SITE:
		raise RuntimeError("refusing non-test site")
	with socket.socket() as sock:
		if sock.connect_ex(("127.0.0.1", 8000)) == 0:
			raise RuntimeError("test port already in use")
	frappe.set_user("Administrator")
	tag = secrets.token_hex(4)
	password = "Stage!" + secrets.token_urlsafe(22)
	teacher = BaseTestUtils._create_user(f"teacher-{tag}@example.invalid", "Test", "Teacher", ["Course Creator"])
	student = BaseTestUtils._create_user(f"student-{tag}@example.invalid", "Test", "Student", ["LMS Student"])
	other = BaseTestUtils._create_user(f"other-{tag}@example.invalid", "Test", "Other", ["LMS Student"])
	for user in (student, other):
		user.new_password = password
		user.save(ignore_permissions=True)
	course = BaseTestUtils._create_course(title="HTTP Access Test " + tag, instructor=teacher.email)
	chapter = BaseTestUtils._create_chapter("HTTP Test Chapter " + tag, course.name)
	BaseTestUtils._create_chapter_reference(course.name, chapter.name)
	lesson = BaseTestUtils._create_lesson("HTTP Test Lesson " + tag, chapter.name, course.name)
	BaseTestUtils._create_lesson_reference(chapter.name, lesson.name)
	for user in (student, other):
		BaseTestUtils._create_enrollment(user.email, course.name)
	frappe.db.set_value("Course Lesson", lesson.name, "youtube", "https://example.invalid/video")
	frappe.get_doc({"doctype": "LMS Access Policy", "course": course.name, "enabled": 1}).insert(ignore_permissions=True)
	frappe.get_doc({"doctype": "LMS Access Grant", "member": student.email, "course": course.name,
		"status": "Active", "starts_at": add_to_date(now_datetime(), days=-1),
		"personal_end_type": "Unlimited", "course_end_type": "Unlimited",
		"lessons": [{"lesson": lesson.name, "opening_type": "At", "opens_at": add_to_date(now_datetime(), days=-1),
			"prerequisite_state": "Clear"}]}).insert(ignore_permissions=True)
	frappe.set_user(teacher.email)
	file_doc = save_file("http-stage-" + tag + ".txt", b"isolated-stage-media", "Course Lesson", lesson.name, is_private=1)
	file_doc.db_set("attached_to_field", "content")
	frappe.set_user("Administrator")
	frappe.db.commit()
	server = None
	checks = {}
	try:
		bench_config(True)
		server = subprocess.Popen(["bench", "serve", "--port", "8000", "--noreload"], cwd=ROOT,
			stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
		deadline = time.monotonic() + 35
		while time.monotonic() < deadline:
			with socket.socket() as sock:
				if sock.connect_ex(("127.0.0.1", 8000)) == 0:
					break
			if server.poll() is not None:
				raise RuntimeError("test web server stopped")
			time.sleep(0.25)
		else:
			raise RuntimeError("test web server did not start")
		clients = []
		for user in (student, other):
			opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
			form = urllib.parse.urlencode({"usr": user.email, "pwd": password}).encode()
			status, _ = call(opener, "/api/method/login", form)
			if status != 200:
				raise RuntimeError("synthetic student login failed")
			clients.append(opener)
		query = urllib.parse.urlencode({"course": course.name, "chapter": 1, "lesson": 1})
		open_status, open_raw = call(clients[0], "/api/method/lms.lms.utils.get_lesson?" + query)
		closed_status, closed_raw = call(clients[1], "/api/method/lms.lms.utils.get_lesson?" + query)
		checks["allowed_lesson"] = open_status == 200 and not json.loads(open_raw)["message"].get("no_preview")
		checks["denied_lesson"] = closed_status == 200 and bool(json.loads(closed_raw)["message"].get("no_preview"))
		query = urllib.parse.urlencode({"course": course.name, "progress": 1})
		status, raw = call(clients[1], "/api/method/lms.lms.utils.get_course_outline?" + query)
		row = json.loads(raw)["message"][0]["lessons"][0]
		checks["outline_masks_video"] = status == 200 and row.get("locked") == 1 and row.get("youtube") is None
		path = "/api/method/lms.lms.doctype.course_lesson.course_lesson.serve_resource?" + urllib.parse.urlencode({"file_url": file_doc.file_url})
		allowed_status, allowed_body = call(clients[0], path)
		denied_status, _ = call(clients[1], path)
		checks["allowed_private_file"] = allowed_status == 200 and allowed_body == b"isolated-stage-media"
		checks["denied_private_file"] = denied_status in (401, 403)
		path = "/api/resource/Course%20Lesson/" + urllib.parse.quote(lesson.name, safe="")
		status, _ = call(clients[1], path)
		checks["denied_direct_document"] = status in (401, 403)
	finally:
		if server:
			server.terminate()
			try:
				server.wait(timeout=10)
			except subprocess.TimeoutExpired:
				server.kill()
				server.wait()
		bench_config(False)
	print(json.dumps({"site": SITE, "checks": checks, "ok": bool(checks) and all(checks.values())}))
	if not checks or not all(checks.values()):
		raise RuntimeError("one or more HTTP access checks failed")


if __name__ == "__main__":
	frappe.init(site=SITE)
	frappe.connect()
	try:
		main()
	finally:
		frappe.destroy()
