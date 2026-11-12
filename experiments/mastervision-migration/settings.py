"""Seal existing unpublished Master Vision courses against self-enrollment.

Only disable_self_learning may change. No publication, grants, enrollments,
source downloads, logs, retries, or backend changes occur here.
"""
import hashlib
import json

from covers import _binding, _course, _course_identity
from importer import Review, Stop, source_id


def _protected(doc):
    def visit(value, top=False):
        if isinstance(value, dict):
            return {key: visit(item) for key, item in value.items()
                    if key not in {'modified', 'modified_by'}
                    and not (top and key == 'disable_self_learning')}
        if isinstance(value, list): return [visit(item) for item in value]
        return value
    try:
        raw = json.dumps(visit(doc, True), ensure_ascii=True, sort_keys=True, allow_nan=False).encode('utf-8')
        return hashlib.sha256(raw).hexdigest()
    except (ValueError, TypeError, RecursionError):
        raise Stop('private_settings_response_invalid') from None


def _write(client, name, modified):
    _binding(client)
    if not isinstance(name, str) or not name or not isinstance(modified, str) or not modified:
        raise Stop('private_settings_update_invalid')
    try:
        response = client.rpc('tools/call', {'name': 'update_document', 'arguments': {
            'doctype': 'LMS Course', 'name': name,
            'data': {'disable_self_learning': 1, 'modified': modified}}})
    except Exception:
        raise Stop('private_settings_write_uncertain') from None
    if (not isinstance(response, dict) or response.get('isError')
            or not isinstance(response.get('structuredContent'), dict)):
        raise Stop('private_settings_write_uncertain')
    return response['structuredContent']


def _verify(doc, course_id, name, protected):
    _course_identity(doc, course_id, name)
    if (type(doc.get('disable_self_learning')) is not int or doc['disable_self_learning'] != 1
            or _protected(doc) != protected):
        raise Stop('private_settings_readback_mismatch')


def ensure_private_course(client, course_id, apply=False):
    """Return ID/status metadata only; apply=False never writes."""
    _binding(client)
    cid = source_id(course_id)
    if type(apply) is not bool: raise Review('private_settings_apply_invalid')
    before = _course(client, cid)
    value = before.get('disable_self_learning')
    if type(value) is not int or value not in (0, 1):
        raise Review('private_settings_value_invalid')
    protected = _protected(before)
    if value == 1:
        return {'course_id': cid, 'status': 'already_private'}
    if not apply:
        return {'course_id': cid, 'status': 'ready'}
    updated = _write(client, before['name'], before['modified'])
    _verify(updated, cid, before['name'], protected)
    try:
        _binding(client)
        final = client.call('get_document', {'doctype': 'LMS Course', 'name': before['name']})
    except Exception:
        raise Stop('private_settings_readback_uncertain') from None
    _verify(final, cid, before['name'], protected)
    return {'course_id': cid, 'status': 'updated'}
