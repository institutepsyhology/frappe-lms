"""Private File preparation and lesson binding for the reviewed IOMP audio manifest."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import urllib.error
import urllib.request
from urllib.parse import urlsplit


SITE = 'my-lk.iomp.ru'
SOURCE_MANIFEST = '22a785bc981f95aa29d2b6b0f6bcd46e3a68a9d49923eaf7a878f53a78457fbb'
MAX_SIZE = 25 * 1024 * 1024


class AudioError(ValueError):
    pass


def target(row):
    if not isinstance(row, dict) or set(row) != {'lesson_id', 'url'}:
        raise AudioError('iomp_audio_source_invalid')
    lesson, source = row['lesson_id'], row['url']
    if (lesson not in {str(n) for n in range(1829, 1839)} or not isinstance(source, str)
            or len(source) > 4096 or not source.isascii() or re.search(r'[\x00-\x20\x7f\\?#]', source)):
        raise AudioError('iomp_audio_source_invalid')
    url = urlsplit(source)
    if (url.scheme, url.netloc) != ('https', 'f1.autoweboffice.ru') or not url.path.lower().endswith('.mp3'):
        raise AudioError('iomp_audio_source_invalid')
    key = hashlib.sha256(source.encode()).hexdigest()
    return '/private/files/avo-iomp-91-' + lesson + '-' + key + '.mp3'


def check_manifest(rows):
    if not isinstance(rows, list) or len(rows) != 62:
        raise AudioError('iomp_audio_manifest_changed')
    pairs = []
    for row in rows:
        target(row)
        pairs.append((row['lesson_id'], hashlib.sha256(row['url'].encode()).hexdigest()))
    encoded = json.dumps(sorted(pairs), separators=(',', ':')).encode()
    if hashlib.sha256(encoded).hexdigest() != SOURCE_MANIFEST:
        raise AudioError('iomp_audio_manifest_changed')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def audio_bytes_valid(data):
    if not isinstance(data, bytes) or not 10 <= len(data) <= MAX_SIZE:
        return False
    if data.startswith(b'ID3'):
        if data[3] not in (2, 3, 4) or data[4] == 255 or max(data[6:10]) >= 128:
            return False
        length = sum(byte << bits for byte, bits in zip(data[6:10], (21, 14, 7, 0)))
        return length + 10 <= len(data)
    return (data[0] == 255 and data[1] & 224 == 224 and (data[1] >> 3) & 3 != 1
            and (data[1] >> 1) & 3 != 0 and data[2] >> 4 not in (0, 15) and (data[2] >> 2) & 3 != 3)


def download(row, limit, directory):
    target(row)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        req = urllib.request.Request(row['url'], headers={'Accept-Encoding': 'identity', 'Accept': 'audio/mpeg'})
        with opener.open(req, timeout=45) as response:
            if (response.status != 200 or response.geturl() != row['url']
                    or response.headers.get_content_type() != 'audio/mpeg'):
                raise AudioError('iomp_audio_response_invalid')
            length = response.headers.get('Content-Length', '')
            if not re.fullmatch(r'[0-9]{1,10}', length) or not 10 <= int(length) <= min(limit, MAX_SIZE):
                raise AudioError('iomp_audio_size_invalid')
            if shutil.disk_usage(directory).free < int(length) + 128 * 1024 * 1024:
                raise AudioError('iomp_audio_space_low')
            data = response.read(int(length) + 1)
    except (OSError, urllib.error.URLError):
        raise AudioError('iomp_audio_source_unavailable') from None
    if len(data) != int(length) or not audio_bytes_valid(data):
        raise AudioError('iomp_audio_content_invalid')
    return data


def names(db, doctype, filters):
    return db.get_all(doctype, filters=filters, pluck='name', limit_page_length=2)


def lesson_name(db, row, required_url):
    found = []
    for doctype, ident in [('LMS Course', '91'), ('Course Lesson', row['lesson_id'])]:
        matched = names(db, doctype, {'custom_avo_account': 'iomp', 'custom_avo_id': ident, 'custom_lms_id': ident})
        if len(matched) != 1:
            raise AudioError('iomp_audio_lesson_identity_invalid')
        found.append(db.get_doc(doctype, matched[0]))
    course, lesson = found
    if (course.published or lesson.course != course.name or not lesson.is_draft
            or lesson.include_in_preview or required_url not in (lesson.content or '')):
        raise AudioError('iomp_audio_lesson_reference_invalid')
    return lesson.name


def validate_saved(db, file, row, *, expecting_attachment=False, expected_hash=None):
    url = target(row)
    if (file.owner != 'Administrator' or file.is_private != 1 or file.file_url != url
            or file.file_name != url.rsplit('/', 1)[-1] or file.is_folder
            or names(db, 'File', {'file_url': url}) != [file.name]
            or names(db, 'File', {'content_hash': file.content_hash, 'is_private': 1}) != [file.name]
            or names(db, 'DocShare', {'share_doctype': 'File', 'share_name': file.name})):
        raise AudioError('iomp_audio_file_identity_invalid')
    attached = (file.attached_to_doctype, file.attached_to_name, file.attached_to_field)
    if any(attached) or expecting_attachment:
        if attached != ('Course Lesson', lesson_name(db, row, url), 'content'):
            raise AudioError('iomp_audio_attachment_conflict')
    content = file.get_content(encodings=[])
    if (not audio_bytes_valid(content) or len(content) != file.file_size
            or hashlib.md5(content, usedforsecurity=False).hexdigest() != file.content_hash
            or expected_hash and hashlib.sha256(content).digest() != expected_hash):
        raise AudioError('iomp_audio_file_readback_invalid')


def sync_one(db, row, mode, limit, directory):
    url = target(row)
    filename = url.rsplit('/', 1)[-1]
    existing = names(db, 'File', {'file_url': url})
    expected = None
    if existing:
        if len(existing) != 1:
            raise AudioError('iomp_audio_file_identity_invalid')
        file = db.get_doc('File', existing[0])
    elif mode == 'prepare':
        if names(db, 'File', {'file_name': filename}) or (directory / filename).exists():
            raise AudioError('iomp_audio_file_conflict')
        data = download(row, limit, directory)
        md5 = hashlib.md5(data, usedforsecurity=False).hexdigest()
        if names(db, 'File', {'content_hash': md5, 'is_private': 1}):
            raise AudioError('iomp_audio_blob_conflict')
        expected = hashlib.sha256(data).digest()
        file = db.get_doc({'doctype': 'File', 'file_name': filename, 'is_private': 1, 'content': data}).insert()
        file = db.get_doc('File', file.name)
    else:
        raise AudioError('iomp_audio_preparation_missing')
    validate_saved(db, file, row, expected_hash=expected)
    if mode == 'attach' and not file.attached_to_name:
        file.attached_to_name = lesson_name(db, row, url)
        file.attached_to_doctype = 'Course Lesson'
        file.attached_to_field = 'content'
        file.save()
        validate_saved(db, db.get_doc('File', file.name), row, expecting_attachment=True)


def main():
    import fcntl
    import frappe
    from frappe.core.api.file import get_max_file_size

    active = None
    try:
        request = json.loads(sys.stdin.buffer.read(300001))
        if set(request) != {'mode', 'rows'} or request['mode'] not in ('prepare', 'attach'):
            raise AudioError('iomp_audio_request_invalid')
        rows, mode = request['rows'], request['mode']
        check_manifest(rows)
        frappe.init(site=SITE)
        frappe.connect()
        frappe.set_user('Administrator')
        directory = Path(frappe.get_site_path('private', 'files')).resolve(strict=True)
        if directory.parts[-3:] != (SITE, 'private', 'files'):
            raise AudioError('iomp_audio_site_mismatch')
        # Serialise concurrent copies/attachments and retain a committed checkpoint per MP3.
        with (directory.parent / 'iomp-course-91-audio.lock').open('a+b') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            limit = get_max_file_size()
            for row in rows:
                active = row['lesson_id']
                sync_one(frappe, row, mode, limit, directory)
                frappe.db.commit()
        print(json.dumps({'mode': mode, 'verified': len(rows)}))
        return 0
    except Exception as error:
        if getattr(frappe.local, 'db', None):
            frappe.db.rollback()
        code = str(error) if isinstance(error, AudioError) else 'iomp_audio_worker_failed'
        print(json.dumps({'code': code, 'lesson_id': active}))
        return 1
    finally:
        frappe.destroy()


if __name__ == '__main__':
    sys.exit(main())
