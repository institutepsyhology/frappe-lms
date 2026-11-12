"""Copy confirmed raster covers to one private Master Vision course via MCP.

No downloads, source URLs, logging, retries, deletion, or backend changes.
An uncertain mutation is fatal and leaves any created File for inspection.
"""
import base64
import hashlib
import json
import re
from urllib.parse import unquote, urlsplit

from assets import _inspect
from importer import ACCOUNT, SITE, Review, Stop, source_id

FILE_FIELDS = ['name', 'file_name', 'file_url', 'is_private', 'attached_to_doctype',
               'attached_to_name', 'attached_to_field', 'content_hash', 'file_size']


def _binding(client):
    if (ACCOUNT, SITE) != ('mastervision', 'my-lk.mastervision.su') or (
            getattr(client, 'account', None), getattr(client, 'site', None)) != (ACCOUNT, SITE):
        raise Stop('wrong_frappe_site')


def _read(client, tool, arguments):
    _binding(client)
    try:
        result = client.call(tool, arguments)
    except Exception:
        raise Stop('cover_read_failed') from None
    if not isinstance(result, dict): raise Stop('cover_read_response_invalid')
    return result


def _write(client, tool, arguments):
    _binding(client)
    if tool == 'create_document':
        data = arguments.get('data', {})
        if (set(arguments) != {'doctype', 'data'} or arguments['doctype'] != 'File'
                or set(data) != {'file_name', 'content', 'decode', 'is_private', 'attached_to_doctype', 'attached_to_name', 'attached_to_field'}
                or data['decode'] != 1 or data['is_private'] != 0
                or data['attached_to_doctype'] != 'LMS Course' or data['attached_to_field'] != 'image'):
            raise Stop('cover_mutation_not_allowed')
    elif tool == 'update_document':
        if (set(arguments) != {'doctype', 'name', 'data'} or arguments['doctype'] != 'LMS Course'
                or set(arguments['data']) != {'image', 'modified'}):
            raise Stop('cover_mutation_not_allowed')
    else:
        raise Stop('cover_mutation_not_allowed')
    try:
        response = client.rpc('tools/call', {'name': tool, 'arguments': arguments})
    except Exception:
        raise Stop('cover_write_uncertain') from None
    if (not isinstance(response, dict) or response.get('isError')
            or not isinstance(response.get('structuredContent'), dict)):
        raise Stop('cover_write_uncertain')
    return response['structuredContent']


def _course_identity(doc, cid, name=None):
    if (not isinstance(doc, dict) or not isinstance(doc.get('name'), str) or not doc['name']
            or doc.get('custom_avo_account') != ACCOUNT or doc.get('custom_avo_id') != cid
            or doc.get('custom_lms_id') != cid or type(doc.get('published')) is not int or doc['published'] != 0
            or (name is not None and doc['name'] != name)):
        raise Stop('cover_course_identity_invalid')


def _course(client, cid):
    data = _read(client, 'list_documents', {'doctype': 'LMS Course',
        'fields': ['name', 'published', 'custom_avo_account', 'custom_avo_id', 'custom_lms_id'],
        'filters': [['custom_avo_account', '=', ACCOUNT], ['custom_avo_id', '=', cid]], 'limit': 3})
    rows = data.get('documents')
    if not isinstance(rows, list) or data.get('has_next_page') is not False or len(rows) > 1:
        raise Review('cover_course_ambiguous')
    if not rows: raise Review('cover_course_missing')
    _course_identity(rows[0], cid)
    doc = _read(client, 'get_document', {'doctype': 'LMS Course', 'name': rows[0]['name']})
    _course_identity(doc, cid, rows[0]['name'])
    if doc.get('doctype') != 'LMS Course' or not isinstance(doc.get('modified'), str) or not doc['modified']:
        raise Stop('cover_course_identity_invalid')
    if doc.get('image') is not None and not isinstance(doc.get('image'), str):
        raise Review('cover_course_image_invalid')
    return doc


def _content(doc):
    # Course save updates timestamps on its child rows too. Attachment audit
    # comments are expected; every content/settings field remains compared.
    def visit(value, top=False):
        if isinstance(value, dict):
            return {key: visit(item) for key, item in value.items()
                    if key not in {'modified', 'modified_by'} and
                    not (top and key in {'image', '_comments', '_comment_count'})}
        if isinstance(value, list): return [visit(item) for item in value]
        return value
    try: return json.dumps(visit(doc, True), ensure_ascii=True, sort_keys=True, allow_nan=False)
    except (ValueError, TypeError, RecursionError): raise Stop('cover_course_response_invalid') from None


def _local_public_url(value):
    if not isinstance(value, str) or not value: return False
    try:
        url = urlsplit(value); decoded = unquote(url.path)
    except ValueError: return False
    return (not url.scheme and not url.netloc and not url.query and not url.fragment
            and decoded.startswith('/files/') and len(decoded) > len('/files/')
            and decoded[len('/files/'):] not in {'.', '..'}
            and '/' not in decoded[len('/files/'):] and '\\' not in decoded
            and not any(ord(char) < 32 for char in decoded))


def _owned(file, cid, course):
    return (isinstance(file, dict) and isinstance(file.get('name'), str) and bool(file['name'])
            and isinstance(file.get('file_name'), str)
            and re.fullmatch(r'avo-mastervision-course-' + re.escape(cid) + r'-[0-9a-f]{16}(?:_[0-9a-f]{6})?\.(jpg|png|webp)', file['file_name'])
            and file.get('attached_to_doctype') == 'LMS Course' and file.get('attached_to_name') == course
            and file.get('attached_to_field') == 'image' and type(file.get('is_private')) is int and file['is_private'] == 0
            and _local_public_url(file.get('file_url')))


def _files(client, filters):
    data = _read(client, 'list_documents', {'doctype': 'File', 'fields': FILE_FIELDS,
                                         'filters': filters, 'limit': 3})
    rows = data.get('documents')
    if not isinstance(rows, list) or data.get('has_next_page') is not False or len(rows) > 1:
        raise Review('cover_file_ambiguous')
    return rows


def _verify_file(file, cid, course, stem, extension, size, md5):
    if (not _owned(file, cid, course) or not re.fullmatch(re.escape(stem) + r'(?:_[0-9a-f]{6})?\.' + extension, file['file_name'])
            or file.get('content_hash') != md5 or type(file.get('file_size')) is not int or file['file_size'] != size):
        raise Stop('cover_file_readback_invalid')


def sync_cover(client, course_id, raw: bytes, extension: str, apply=False):
    """Return metadata only; apply=False performs no mutation."""
    _binding(client)
    cid = source_id(course_id)
    if type(apply) is not bool or extension not in ('jpg', 'png', 'webp'):
        raise Review('cover_input_invalid')
    if _inspect(raw) != extension: raise Review('cover_image_type_mismatch')
    sha, md5 = hashlib.sha256(raw).hexdigest(), hashlib.md5(raw, usedforsecurity=False).hexdigest()
    stem = f'avo-mastervision-course-{cid}-{sha[:16]}'
    filename = stem + '.' + extension
    original = _course(client, cid)
    name, content, old_image = original['name'], _content(original), original.get('image') or None
    metadata = {'course_id': cid, 'sha256': sha, 'bytes': len(raw), 'file_created': False}
    attachment = [['attached_to_doctype', '=', 'LMS Course'], ['attached_to_name', '=', name],
                  ['attached_to_field', '=', 'image']]
    if old_image:
        if not _local_public_url(old_image):
            return {**metadata, 'status': 'skipped_existing_cover'}
        rows = _files(client, [*attachment, ['file_url', '=', old_image]])
        if not rows or not _owned(rows[0], cid, name):
            return {**metadata, 'status': 'skipped_existing_cover'}
    candidates = _files(client, [*attachment, ['file_name', 'like', stem + '%']])
    file = candidates[0] if candidates else None
    if file is not None:
        _verify_file(file, cid, name, stem, extension, len(raw), md5)
        file = _read(client, 'get_document', {'doctype': 'File', 'name': file['name']})
        _verify_file(file, cid, name, stem, extension, len(raw), md5)
    if file is not None and old_image == file['file_url']:
        return {**metadata, 'status': 'already_imported'}
    if not apply:
        return {**metadata, 'status': 'ready'}
    if file is None:
        file = _write(client, 'create_document', {'doctype': 'File', 'data': {
            'file_name': filename, 'content': base64.b64encode(raw).decode('ascii'), 'decode': 1,
            'is_private': 0, 'attached_to_doctype': 'LMS Course', 'attached_to_name': name,
            'attached_to_field': 'image'}})
        metadata['file_created'] = True
        _verify_file(file, cid, name, stem, extension, len(raw), md5)
        readback = _read(client, 'get_document', {'doctype': 'File', 'name': file['name']})
        _verify_file(readback, cid, name, stem, extension, len(raw), md5)
        if any(readback.get(key) != file.get(key) for key in FILE_FIELDS):
            raise Stop('cover_file_readback_invalid')
        file = readback
    # Recheck before the update and supply modified as Frappe's optimistic
    # concurrency condition, so a later manual cover change is not overwritten.
    before_update = _read(client, 'get_document', {'doctype': 'LMS Course', 'name': name})
    _course_identity(before_update, cid, name)
    if _content(before_update) != content or (before_update.get('image') or None) != old_image:
        raise Stop('cover_course_changed')
    updated = _write(client, 'update_document', {'doctype': 'LMS Course', 'name': name,
        'data': {'image': file['file_url'], 'modified': before_update['modified']}})
    _course_identity(updated, cid, name)
    if updated.get('image') != file['file_url'] or _content(updated) != content:
        raise Stop('cover_course_readback_invalid')
    final = _read(client, 'get_document', {'doctype': 'LMS Course', 'name': name})
    _course_identity(final, cid, name)
    if final.get('image') != file['file_url'] or _content(final) != content:
        raise Stop('cover_course_readback_invalid')
    return {**metadata, 'status': 'created' if metadata['file_created'] else 'updated'}
